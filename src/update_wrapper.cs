// Stable native launcher for the public ChatGPTnx.exe.
// The Python/PyInstaller core is an embedded payload and never replaces this
// process while it is running. This also makes the first upgrade from the
// previous one-file release independent of its inherited PyInstaller state.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Windows.Forms;

internal static class ChatGPTnxLauncher
{
    private const string PayloadName = "ChatGPTnx.Core.exe";
    private const string PayloadVersion = "__PAYLOAD_VERSION__";
    private const string PayloadSha256 = "__PAYLOAD_SHA256__";

    private static string Quote(string value)
    {
        return "\"" + value.Replace("\"", "") + "\"";
    }

    private static string Digest(string path)
    {
        using (var sha = SHA256.Create())
        using (var stream = File.OpenRead(path))
            return BitConverter.ToString(sha.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();
    }

    private static string Root()
    {
        return AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
    }

    private static string MaterializePayload(string root)
    {
        var directory = Path.Combine(root, "_wip", "runtime", PayloadVersion);
        Directory.CreateDirectory(directory);
        var target = Path.Combine(directory, PayloadName);
        if (!File.Exists(target) || !String.Equals(Digest(target), PayloadSha256, StringComparison.OrdinalIgnoreCase))
        {
            var temp = target + "." + Guid.NewGuid().ToString("N") + ".tmp";
            using (var input = typeof(ChatGPTnxLauncher).Assembly.GetManifestResourceStream(PayloadName))
            {
                if (input == null) throw new InvalidDataException("embedded_core_missing");
                using (var output = File.Create(temp)) input.CopyTo(output);
            }
            if (!String.Equals(Digest(temp), PayloadSha256, StringComparison.OrdinalIgnoreCase))
            {
                File.Delete(temp);
                throw new InvalidDataException("embedded_core_checksum_failed");
            }
            if (File.Exists(target)) File.Replace(temp, target, null, true);
            else File.Move(temp, target);
        }
        return target;
    }

    private static Process StartCore(string core, string root, string[] args)
    {
        var forwarded = new List<string>(args);
        forwarded.Add("--home"); forwarded.Add(root);
        forwarded.Add("--launcher-executable"); forwarded.Add(Path.Combine(root, "ChatGPTnx.exe"));
        forwarded.Add("--launcher-pid"); forwarded.Add(Process.GetCurrentProcess().Id.ToString());
        var start = new ProcessStartInfo {
            FileName = core,
            Arguments = String.Join(" ", forwarded.Select(Quote)),
            WorkingDirectory = root,
            UseShellExecute = false,
            CreateNoWindow = true,
            WindowStyle = ProcessWindowStyle.Hidden
        };
        var remove = new List<string>();
        foreach (var key in start.EnvironmentVariables.Keys)
        {
            var name = (string)key;
            if (name.StartsWith("_PYI_", StringComparison.OrdinalIgnoreCase)
                    || name.Equals("_MEIPASS2", StringComparison.OrdinalIgnoreCase)
                    || name.Equals("PYINSTALLER_RESET_ENVIRONMENT", StringComparison.OrdinalIgnoreCase))
                remove.Add(name);
        }
        foreach (var key in remove) start.EnvironmentVariables.Remove(key);
        start.EnvironmentVariables["PYINSTALLER_RESET_ENVIRONMENT"] = "1";
        start.EnvironmentVariables["CHATGPTNX_LAUNCHER_EXE"] = Path.Combine(root, "ChatGPTnx.exe");
        return Process.Start(start);
    }

    public static int Main(string[] args)
    {
        try
        {
            var root = Root();
            var core = MaterializePayload(root);
            using (var process = StartCore(core, root, args))
            {
                process.WaitForExit();
                return process.ExitCode;
            }
        }
        catch (Exception error)
        {
            try { MessageBox.Show("ChatGPTnx 启动失败：" + error.GetType().Name, "ChatGPTnx", MessageBoxButtons.OK, MessageBoxIcon.Error); }
            catch { }
            return 1;
        }
    }
}
