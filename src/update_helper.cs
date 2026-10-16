// Independent Windows updater for the one-file ChatGPTnx build.
// It must not load the Python/PyInstaller runtime that it is replacing.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;

internal static class UpdateHelper
{
    private const int WaitParentMs = 45000;
    private const int WaitStartMs = 45000;

    private static string Arg(string[] args, string name)
    {
        for (var i = 0; i + 1 < args.Length; i++)
            if (String.Equals(args[i], name, StringComparison.OrdinalIgnoreCase)) return args[i + 1];
        throw new InvalidDataException("missing_argument");
    }

    private static string Full(string value)
    {
        return Path.GetFullPath(value ?? "").TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
    }

    private static void Plain(string path)
    {
        var info = new FileInfo(path);
        if ((info.Attributes & FileAttributes.ReparsePoint) != 0) throw new IOException("unsafe_path");
    }

    private static string Digest(string path)
    {
        using (var sha = SHA256.Create())
        using (var stream = File.OpenRead(path))
            return BitConverter.ToString(sha.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();
    }

    private static Dictionary<string, object> ReadPlan(string path)
    {
        var raw = File.ReadAllText(path, Encoding.UTF8);
        var value = new JavaScriptSerializer().DeserializeObject(raw) as Dictionary<string, object>;
        if (value == null) throw new InvalidDataException("invalid_plan");
        return value;
    }

    private static string StringValue(Dictionary<string, object> plan, string key, bool required = true)
    {
        object value;
        if (!plan.TryGetValue(key, out value) || !(value is string) || String.IsNullOrEmpty((string)value))
        {
            if (required) throw new InvalidDataException("invalid_plan_" + key);
            return "";
        }
        return (string)value;
    }

    private static long LongValue(Dictionary<string, object> plan, string key, bool required = true)
    {
        object value;
        if (!plan.TryGetValue(key, out value))
        {
            if (required) throw new InvalidDataException("invalid_plan_" + key);
            return 0;
        }
        try { return Convert.ToInt64(value); }
        catch { if (required) throw new InvalidDataException("invalid_plan_" + key); return 0; }
    }

    private static void WritePlan(string path, Dictionary<string, object> plan)
    {
        var json = new JavaScriptSerializer().Serialize(plan);
        var temp = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        File.WriteAllText(temp, json, new UTF8Encoding(false));
        File.Replace(temp, path, null, true);
    }

    private static Process StartApp(string target, string root, string runtime, string ack, string token)
    {
        Directory.CreateDirectory(runtime);
        var start = new ProcessStartInfo {
            FileName = target,
            Arguments = "--update-ack " + Quote(ack) + " --update-token " + Quote(token),
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
        start.EnvironmentVariables["TEMP"] = runtime;
        start.EnvironmentVariables["TMP"] = runtime;
        return Process.Start(start);
    }

    private static string Quote(string value)
    {
        return "\"" + value.Replace("\"", "") + "\"";
    }

    private static bool Ack(string path, string token, int versionWait, Process child)
    {
        var deadline = DateTime.UtcNow.AddMilliseconds(versionWait);
        while (DateTime.UtcNow < deadline)
        {
            if (File.Exists(path))
            {
                try
                {
                    var ack = new JavaScriptSerializer().DeserializeObject(File.ReadAllText(path, Encoding.UTF8)) as Dictionary<string, object>;
                    object ready, gotToken;
                    if (ack != null && ack.TryGetValue("ready", out ready) && ready is bool && (bool)ready
                            && ack.TryGetValue("token", out gotToken) && String.Equals(Convert.ToString(gotToken), token, StringComparison.Ordinal))
                        return true;
                }
                catch { }
            }
            if (child != null && child.HasExited) return false;
            Thread.Sleep(250);
        }
        return false;
    }

    private static void Stop(Process child)
    {
        if (child == null || child.HasExited) return;
        try
        {
            var taskkill = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Windows), "System32", "taskkill.exe");
            using (var killer = Process.Start(new ProcessStartInfo {
                FileName = taskkill, Arguments = "/PID " + child.Id + " /T /F", UseShellExecute = false,
                CreateNoWindow = true, WindowStyle = ProcessWindowStyle.Hidden })) killer.WaitForExit(10000);
        }
        catch { try { child.Kill(); } catch { } }
        try { child.WaitForExit(10000); } catch { }
    }

    private static void RemoveTree(string path)
    {
        if (!Directory.Exists(path)) return;
        var deadline = DateTime.UtcNow.AddSeconds(12);
        while (DateTime.UtcNow < deadline)
        {
            try { Directory.Delete(path, true); return; }
            catch { Thread.Sleep(250); }
        }
    }

    private static void Result(string path, string status, string phase, string reason)
    {
        var json = new JavaScriptSerializer().Serialize(new Dictionary<string, object> {
            { "status", status }, { "phase", phase }, { "reason", reason ?? "" }
        });
        File.WriteAllText(path, json, new UTF8Encoding(false));
    }

    private static int Run(string[] args)
    {
        var planPath = Full(Arg(args, "-Plan"));
        var batch = Full(Path.GetDirectoryName(planPath));
        var resultPath = Path.Combine(batch, "result.json");
        var phase = "plan";
        var replaced = false;
        Process candidate = null;
        try
        {
            Plain(batch); Plain(planPath);
            var plan = ReadPlan(planPath);
            var root = Full(StringValue(plan, "root"));
            var target = Full(StringValue(plan, "executable"));
            var updates = Full(Path.Combine(root, "_wip", "update"));
            if (!String.Equals(Full(Path.GetDirectoryName(batch)), updates, StringComparison.OrdinalIgnoreCase)
                    || !String.Equals(Full(Path.GetDirectoryName(target)), root, StringComparison.OrdinalIgnoreCase)
                    || !target.EndsWith(".exe", StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("unsafe_plan");
            Plain(root); Plain(Path.Combine(root, "_wip")); Plain(updates); Plain(target);
            var stage = Path.Combine(batch, "ChatGPTnx.new.exe");
            var backup = Path.Combine(batch, "previous.exe");
            var failed = Path.Combine(batch, "failed.exe");
            var ack = Path.Combine(batch, "started.json");
            var runtime = Path.Combine(batch, "runtime-candidate");
            var token = StringValue(plan, "token");
            var expectedSha = StringValue(plan, "sha256");
            var expectedSize = LongValue(plan, "size");
            var parentPid = LongValue(plan, "parent_pid");
            if (token.Length != 32 || expectedSha.Length != 64 || expectedSize < 1024 || parentPid <= 0)
                throw new InvalidDataException("unsafe_plan");
            Plain(stage);
            if (new FileInfo(stage).Length != expectedSize || !String.Equals(Digest(stage), expectedSha, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("checksum_failed");
            if (new FileInfo(stage).Length < 2 || File.ReadAllBytes(stage).Take(2).SequenceEqual(new byte[] { 0x4D, 0x5A }) == false)
                throw new InvalidDataException("not_windows_program");
            var previousSha = Digest(target);
            var previousSize = new FileInfo(target).Length;
            var previousVersion = StringValue(plan, "previous_version", false);
            if (String.IsNullOrEmpty(previousVersion)) previousVersion = FileVersionInfo.GetVersionInfo(target).FileVersion;
            Process parent = null;
            try { parent = Process.GetProcessById((int)parentPid); } catch { }
            if (parent != null && !parent.WaitForExit(WaitParentMs)) throw new TimeoutException("parent_still_running");
            phase = "replace";
            File.Replace(stage, target, backup, true);
            replaced = true;
            phase = "start";
            candidate = StartApp(target, root, runtime, ack, token);
            if (Ack(ack, token, WaitStartMs, candidate)) { Result(resultPath, "complete", phase, ""); return 0; }
            throw new InvalidDataException("startup_failed");
        }
        catch (Exception error)
        {
            if (replaced)
            {
                phase = "rollback";
                try
                {
                    Stop(candidate);
                    var plan = ReadPlan(planPath);
                    var target = Full(StringValue(plan, "executable"));
                    var root = Full(StringValue(plan, "root"));
                    var rollbackBatch = Full(Path.GetDirectoryName(planPath));
                    var backup = Path.Combine(rollbackBatch, "previous.exe");
                    var failed = Path.Combine(rollbackBatch, "failed.exe");
                    var ack = Path.Combine(rollbackBatch, "started.json");
                    var candidateRuntime = Path.Combine(rollbackBatch, "runtime-candidate");
                    var runtime = Path.Combine(rollbackBatch, "runtime-rollback");
                    RemoveTree(candidateRuntime);
                    plan["sha256"] = Digest(backup);
                    plan["size"] = new FileInfo(backup).Length;
                    plan["version"] = StringValue(plan, "previous_version", false);
                    if (String.IsNullOrEmpty(Convert.ToString(plan["version"]))) plan["version"] = FileVersionInfo.GetVersionInfo(backup).FileVersion;
                    File.Replace(backup, target, failed, true);
                    WritePlan(planPath, plan);
                    var restored = StartApp(target, root, runtime, ack, StringValue(plan, "token"));
                    if (Ack(ack, StringValue(plan, "token"), WaitStartMs, restored))
                    {
                        Result(resultPath, "rolled_back", phase, "startup_failed"); return 2;
                    }
                    Stop(restored);
                    Result(resultPath, "recovery_needed", phase, "rollback_start_failed"); return 3;
                }
                catch (Exception rollbackError)
                {
                    Result(resultPath, "recovery_needed", phase, rollbackError.GetType().Name); return 3;
                }
            }
            Result(resultPath, "failed", phase, error.GetType().Name); return 1;
        }
    }

    public static int Main(string[] args) { return Run(args); }
}
