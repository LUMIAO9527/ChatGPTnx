# Page and input classification shared by the native helper and isolated fixtures.
function Get-NXLoginSurface([string]$Url, [array]$Edits, [string]$Text,
                            [array]$Buttons, [bool]$AppHost = $false) {
    $surface = 'none'
    try {
        $uri = [Uri]$Url
        if ($uri.IsAbsoluteUri -and -not $uri.UserInfo) {
            $hostName = $uri.DnsSafeHost.ToLowerInvariant()
            $pathName = $uri.AbsolutePath.ToLowerInvariant()
            $authHost = $hostName -in @('auth.openai.com', 'auth0.openai.com')
            $webHost = $hostName -in @('chatgpt.com', 'chat.openai.com', 'platform.openai.com')
            $loginPath = $pathName -match '^/(log-?in|sign-?in|u/login|u/mfa[^/]*|mfa|verify|email-verification|authorize|auth)(/|$)'
            $otherPath = $pathName -match 'sign-?up|register|create-account|reset-password|forgot|recovery|settings'
            if ($uri.Scheme -eq 'https' -and ($authHost -or $webHost) -and $loginPath -and -not $otherPath) { $surface = 'auth' }
            if ($AppHost -and $uri.Scheme -eq 'app' -and $uri.Host -eq '-' -and $uri.AbsolutePath -eq '/index.html') { $surface = 'app' }
        }
    } catch { }
    $hint = 'none'
    if ($Text -match '(?i)phone number|verify.{0,15}phone|text message|手机号|手机号码|电话验证|短信') { $hint = 'phone' }
    elseif ($Text -match '(?i)captcha|turnstile|verify.{0,15}human|人机|验证你是人类|passkey|security key') { $hint = 'human_check' }
    elseif ($Text -match '(?i)(sent|send).{0,35}(email|e-mail|code|to)|check your (inbox|email)|验证码.{0,15}(邮箱|邮件)|(邮箱|邮件).{0,15}验证码') { $hint = 'email_code' }
    elseif ($Text -match '(?i)authenticator|验证器|身份验证应用') { $hint = 'authenticator' }

    $stage = 'unknown'; $index = -1
    $start = @($Buttons | Where-Object { $_ -match '^(?i:Continue to sign in|继续登录|Sign in with ChatGPT|使用 ChatGPT 登录)$' })
    if ($surface -eq 'app' -and $start.Count -eq 1) { $stage = 'launch' }
    if ($surface -eq 'auth') {
        for ($i = 0; $i -lt $Edits.Count; $i++) {
            $edit = $Edits[$i]
            if ($edit.enabled -eq $false -or $edit.offscreen -eq $true) { continue }
            if ($edit.password -eq $true) { $stage = 'password'; $index = $i; break }
        }
        if ($index -lt 0) {
            for ($i = 0; $i -lt $Edits.Count; $i++) {
                $edit = $Edits[$i]
                if ($edit.enabled -eq $false -or $edit.offscreen -eq $true) { continue }
                $label = [string]$edit.name + ' ' + [string]$edit.id
                if ($label -match '(?i)code|otp|一次性|验证码') { $stage = 'otp'; $index = $i; break }
                if ($label -match '(?i)email|e-mail|username|邮箱|电子邮件') { $stage = 'email'; $index = $i }
            }
        }
    }
    return @{surface=$surface;step=$stage;hint=$hint;index=$index}
}
