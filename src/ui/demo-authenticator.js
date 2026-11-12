/* Local image selection and authenticator decoding for the offline HTML. */
'use strict';
window.NXDemoQR = (() => {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
  const saved = new Map(), pending = new Map(), keys = new Map();
  let serial = 0, queued = null;
  const fail = text => { throw new Error(text); };
  const now = () => Math.floor(Date.now() / 1000);
  const addresses = account => account.name.match(/[^\s:<>]+@[^\s:<>]+/g) || [];
  const supportedIssuer = account => ['', 'openai', 'chatgpt', 'openai.com', 'chatgpt.com']
    .includes(account.issuer.trim().toLowerCase());
  function base32(bytes) {
    let bits = 0, value = 0, result = '';
    for (const byte of bytes) {
      value = (value << 8) | byte; bits += 8;
      while (bits >= 5) { bits -= 5; result += alphabet[(value >>> bits) & 31]; }
    }
    if (bits) result += alphabet[(value << (5 - bits)) & 31];
    return result;
  }
  function secretBytes(text) {
    text = String(text || '').toUpperCase().replace(/[\s=-]/g, '');
    if (!/^[A-Z2-7]{16,512}$/.test(text)) fail('二维码中的验证器密钥无法识别');
    let bits = 0, value = 0; const result = [];
    for (const letter of text) {
      value = (value << 5) | alphabet.indexOf(letter); bits += 5;
      if (bits >= 8) { bits -= 8; result.push((value >>> bits) & 255); }
    }
    return new Uint8Array(result);
  }
  function fields(bytes) {
    let at = 0; const result = [];
    const integer = () => {
      let value = 0n;
      for (let shift = 0n; shift < 70n; shift += 7n) {
        if (at >= bytes.length) fail('二维码内容不完整');
        const byte = bytes[at++]; value |= BigInt(byte & 127) << shift;
        if (!(byte & 128)) return value;
      }
      fail('二维码内容无法识别');
    };
    while (at < bytes.length) {
      const key = Number(integer()), number = key >>> 3, wire = key & 7;
      if (!number) fail('二维码内容无法识别');
      let value;
      if (wire === 0) value = integer();
      else if ([1, 2, 5].includes(wire)) {
        const length = wire === 2 ? Number(integer()) : wire === 1 ? 8 : 4;
        if (length > 131072 || at + length > bytes.length) fail('二维码内容不完整');
        value = bytes.slice(at, at + length); at += length;
      } else fail('二维码内容无法识别');
      result.push({number, wire, value});
    }
    return result;
  }
  function parse(text) {
    let uri;
    try { uri = new URL(text); } catch { fail('请选择验证器二维码图片'); }
    if (uri.protocol === 'otpauth:' && uri.hostname === 'totp') {
      const secret = base32(secretBytes(uri.searchParams.get('secret')));
      if ((uri.searchParams.get('algorithm') || 'SHA1').toUpperCase() !== 'SHA1'
          || (uri.searchParams.get('digits') || '6') !== '6' || (uri.searchParams.get('period') || '30') !== '30') {
        fail('请选择 SHA-1、6 位、30 秒周期的验证器');
      }
      return {accounts: [{name: decodeURIComponent(uri.pathname.slice(1)), issuer: uri.searchParams.get('issuer') || '', secret}], size: 1, index: 0, id: ''};
    }
    if (uri.protocol !== 'otpauth-migration:' || uri.hostname !== 'offline' || uri.searchParams.getAll('data').length !== 1) fail('请选择验证器二维码图片');
    let raw;
    try { raw = Uint8Array.from(atob(uri.searchParams.get('data').replace(/ /g, '+').replace(/-/g, '+').replace(/_/g, '/')), c => c.charCodeAt(0)); }
    catch { fail('二维码内容无法识别'); }
    if (raw.length > 131072) fail('二维码内容过长');
    const accounts = [], metadata = new Map(), decoder = new TextDecoder('utf-8', {fatal: true});
    for (const field of fields(raw)) {
      if (field.number === 1) {
        if (field.wire !== 2 || accounts.length >= 200) fail('二维码账号条目无法识别');
        const values = new Map();
        for (const part of fields(field.value)) {
          if (values.has(part.number)) fail('二维码账号条目无法识别');
          values.set(part.number, part);
        }
        if (![4, 5, 6].every((n, i) => values.get(n)?.wire === 0 && values.get(n)?.value === [1n, 1n, 2n][i])) fail('请选择 SHA-1、6 位、30 秒周期的验证器');
        if (values.get(1)?.wire !== 2 || values.get(1).value.length < 10) fail('二维码中的验证器密钥无法识别');
        accounts.push({secret: base32(values.get(1).value), name: decoder.decode(values.get(2)?.value || new Uint8Array()), issuer: decoder.decode(values.get(3)?.value || new Uint8Array())});
      } else if ([2, 3, 4, 5].includes(field.number)) {
        if (field.wire !== 0 || metadata.has(field.number)) fail('二维码分组无法识别');
        metadata.set(field.number, field.value);
      }
    }
    const size = Number(metadata.get(3) ?? 1n), index = Number(metadata.get(4) ?? 0n);
    if (![1n, 2n].includes(metadata.get(2) ?? 1n) || !accounts.length || size < 1 || size > 50 || index < 0 || index >= size) fail('二维码分组无法识别');
    return {accounts, size, index, id: String(metadata.get(5) ?? 0n)};
  }
  function combine(transfers) {
    const accounts = [], groups = new Map();
    for (const item of transfers) {
      if (item.size === 1) { accounts.push(...item.accounts); continue; }
      const key = item.id + '/' + item.size;
      if (!groups.has(key)) groups.set(key, new Map());
      const group = groups.get(key), previous = group.get(item.index);
      if (previous && JSON.stringify(previous.accounts) !== JSON.stringify(item.accounts)) fail('同组二维码内容不一致');
      group.set(item.index, item);
    }
    for (const group of groups.values()) {
      const size = group.values().next().value.size;
      if (group.size !== size) fail(`这组共有 ${size} 张二维码，请一次选择全部图片`);
      for (let i = 0; i < size; i++) accounts.push(...group.get(i).accounts);
    }
    const unique = [...new Map(accounts.map(a => [JSON.stringify(a), a])).values()];
    if (!unique.length || unique.length > 200) fail('二维码中的账号数量无法识别');
    return unique;
  }
  async function readImages(files) {
    if (!files?.length || files.length > 50) fail('请选择二维码图片');
    const transfers = [];
    for (const file of files) {
      if (file.size > 20 * 1024 * 1024) fail('请选择小于 20 MB 的二维码图片');
      let bitmap;
      try { bitmap = await createImageBitmap(file); } catch { fail('图片无法打开，请选择二维码图片'); }
      try {
        if (bitmap.width * bitmap.height > 24000000) fail('图片过大，请框选二维码后重试');
        const scale = Math.min(1, 1800 / Math.max(bitmap.width, bitmap.height));
        const canvas = document.createElement('canvas'); canvas.width = Math.round(bitmap.width * scale); canvas.height = Math.round(bitmap.height * scale);
        const context = canvas.getContext('2d', {willReadFrequently: true}); context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
        const pixels = context.getImageData(0, 0, canvas.width, canvas.height);
        const code = window.jsQR(pixels.data, pixels.width, pixels.height);
        if (!code) fail('图片中没有识别到二维码，请选择清晰图片');
        transfers.push(parse(code.data));
      } finally { bitmap.close(); }
    }
    return combine(transfers);
  }
  async function choose() {
    if (queued) { const files = queued; queued = null; return readImages(files); }
    const files = await new Promise(resolve => {
      const input = document.createElement('input'); input.type = 'file'; input.multiple = true;
      input.accept = 'image/png,image/jpeg,image/webp,image/bmp'; input.hidden = true;
      input.dataset.demoQrPicker = 'true'; document.body.append(input);
      const finish = value => { input.remove(); resolve(value); };
      input.addEventListener('change', () => finish([...input.files]), {once: true});
      input.addEventListener('cancel', () => finish([]), {once: true}); input.click();
    });
    return files.length ? readImages(files) : null;
  }
  async function clipboard(pasted) {
    if (pasted) return readImages([pasted]);
    const files = [];
    try {
      for (const item of await navigator.clipboard.read()) {
        const type = item.types.find(value => value.startsWith('image/'));
        if (type) files.push(await item.getType(type));
      }
    } catch { fail('请在这里按 Ctrl + V 粘贴截图'); }
    if (!files.length) fail('剪贴板中没有截图，请先复制截图');
    return readImages(files);
  }
  async function code(secret) {
    if (!crypto.subtle) fail('请用 Chrome 打开此 HTML 后读取二维码');
    if (!keys.has(secret)) keys.set(secret, await crypto.subtle.importKey('raw', secretBytes(secret), {name: 'HMAC', hash: 'SHA-1'}, false, ['sign']));
    const buffer = new ArrayBuffer(8); new DataView(buffer).setBigUint64(0, BigInt(Math.floor(now() / 30)));
    const digest = new Uint8Array(await crypto.subtle.sign('HMAC', keys.get(secret), buffer)), offset = digest[19] & 15;
    const value = (((digest[offset] & 127) << 24) | (digest[offset + 1] << 16) | (digest[offset + 2] << 8) | digest[offset + 3]) >>> 0;
    return {code: String(value % 1000000).padStart(6, '0'), remain: 30 - now() % 30};
  }
  async function single(accounts, email) {
    if (!/^[^\s@]+@[^\s@]+$/.test(email || '')) fail('请填写账号邮箱');
    const candidates = accounts.filter(supportedIssuer);
    const matching = candidates.filter(a => {
      const labels = new Set(addresses(a).map(value => value.toLowerCase()));
      return labels.size === 1 && labels.has(email.toLowerCase());
    });
    const only = accounts.length === 1 && candidates.length === 1 && !addresses(candidates[0]).length ? candidates[0] : null;
    const account = matching.length && new Set(matching.map(item => item.secret)).size === 1 ? matching[0] : only;
    if (!account) fail('请选择此账号的 ChatGPT 验证器二维码');
    const token = 'qr-single-' + ++serial, item = {account, email, expires: now() + 900};
    pending.set(token, item);
    return {ok: true, email, token, ...await code(account.secret), expires_at: item.expires,
      source: 'imported', account_matched: !!matching.length};
  }
  function commitSingle(payload) {
    const item = pending.get(payload.token);
    if (!item?.account || item.expires <= now() || item.email !== payload.email || !payload.confirmed) fail('请先完成验证码确认');
    saved.set(item.email.toLowerCase(), item.account.secret); pending.delete(payload.token); return {ok: true};
  }

  function batch(accounts, roster, vault) {
    const emails = new Map(roster.map(({email}) => [email.toLowerCase(), email]));
    const existing = new Set(vault.filter(entry => entry.has_secret).map(entry => entry.email.toLowerCase()));
    const rows = [], candidates = new Map();
    for (const account of accounts) {
      const labels = addresses(account);
      const distinct = new Set(labels.map(email => email.toLowerCase()));
      const email = distinct.size === 1 ? emails.get(labels[0].toLowerCase()) : null;
      const source = labels[0] || account.name || '未标邮箱';
      const problem = !supportedIssuer(account) ? '非 ChatGPT 验证器'
        : distinct.size > 1 ? '二维码包含多个邮箱'
        : !labels.length ? '二维码未标邮箱'
        : !email ? '未找到对应账号' : '';
      if (problem) {
        rows.push({source, problem});
        continue;
      }
      const previous = candidates.get(email);
      if (previous) {
        if (previous.secret !== account.secret) previous.row.problem = '同一邮箱有多个验证器';
        continue;
      }
      const row = {id: String(rows.length), source, email, replaces: existing.has(email.toLowerCase())};
      candidates.set(email, {row, secret: account.secret});
      rows.push(row);
    }
    const entries = new Map();
    for (const {row, secret} of candidates.values()) {
      if (!row.problem) entries.set(row.id, {email: row.email, secret});
    }
    const token = 'qr-batch-' + ++serial;
    pending.set(token, {entries, expires: now() + 900});
    return {ok: true, token, rows};
  }

  async function commitBatch({token, selections}, accountExists) {
    const item = pending.get(token);
    if (!item?.entries || item.expires <= now()) fail('请重新选择二维码图片');
    if (!Array.isArray(selections) || !selections.length) fail('请至少选择一个账号');
    const entries = selections.map(selection => item.entries.get(selection?.id));
    if (new Set(entries).size !== entries.length
        || entries.some((entry,index) => !entry || entry.email !== selections[index]?.email)) fail('请重新核对所选账号');
    const records = await Promise.all(entries.map(async entry => ({email: entry.email, ...await code(entry.secret)})));
    if (pending.get(token) !== item || item.expires <= now()) fail('请重新选择二维码图片');
    if (!entries.every(entry => accountExists(entry.email))) fail('账号列表已更新，请重新选择二维码图片');
    for (const {email, secret} of entries) saved.set(email.toLowerCase(), secret);
    pending.delete(token);
    return records;
  }
  async function refresh(vault, previews) {
    for (const entry of vault) {
      const secret = saved.get(entry.email.toLowerCase()); if (secret) Object.assign(entry, await code(secret));
    }
    for (const entry of previews) {
      const item = pending.get(entry.token); if (item?.account) Object.assign(entry, await code(item.account.secret));
    }
  }
  const hasExample = key => Object.hasOwn(window.NX_DEMO_IMAGES || {}, key);
  function example(key) {
    if (!hasExample(key)) return false;
    const uri = window.NX_DEMO_IMAGES[key];
    const raw = Uint8Array.from(atob(uri.split(',')[1]), c => c.charCodeAt(0));
    queued = [new File([raw], 'NX-演示二维码.png', {type: 'image/png'})];
    return true;
  }
  return {choose, clipboard, single, commitSingle, batch, commitBatch, refresh, example, hasExample,
    cancel: token => pending.delete(token), reset: () => {saved.clear();pending.clear();keys.clear();queued=null;}};
})();
