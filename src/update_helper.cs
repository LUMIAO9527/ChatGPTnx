// Independent transaction owner. No dependency on the Python runtime it replaces.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using System.Threading;

internal static class UpdateHelper
{
    private const int WaitParentMs = 45000;
    private const int WaitStartMs = 45000;
    private static string root, batch, target, token, version, previousVersion, previousSha;
    private static long previousSize;
    private static Dictionary<string, object> plan;

    private static void Result(string status, string phase, string reason, string recovery = "")
    {
        UpdateFiles.Write(UpdateFiles.Child(batch, "result.json"), new Dictionary<string, object> {
            { "schema", 2 }, { "status", status }, { "phase", phase }, { "reason", reason },
            { "version", version ?? "" }, { "token", token ?? "" },
            { "finished_at", DateTime.UtcNow.ToString("o") }, { "recovery_batch", recovery }
        });
    }

    private static void Verify(string path, long size, string sha)
    {
        UpdateFiles.Plain(path);
        if (!Regex.IsMatch(sha, "^[0-9a-f]{64}$") || size < 1024 || size > 150L * 1024 * 1024
                || new FileInfo(path).Length != size || UpdateFiles.Digest(path) != sha)
            throw new InvalidDataException("checksum_failed");
        using (var stream = File.OpenRead(path))
            if (stream.ReadByte() != 0x4D || stream.ReadByte() != 0x5A) throw new InvalidDataException("not_windows_program");
    }

    private static Process FindParent(long pid)
    {
        if (pid <= 0 || pid > Int32.MaxValue || pid == Process.GetCurrentProcess().Id) throw new InvalidDataException("invalid_parent");
        try { return Process.GetProcessById((int)pid); } catch (ArgumentException) { return null; }
    }

    private static Process StartApp(string runtime, string ack, string ackToken)
    {
        UpdateFiles.Plain(runtime); Directory.CreateDirectory(runtime);
        var start = new ProcessStartInfo {
            FileName = target, Arguments = "--update-ack " + UpdateFiles.Quote(ack) + " --update-token " + UpdateFiles.Quote(ackToken),
            WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = true, WindowStyle = ProcessWindowStyle.Hidden
        };
        UpdateFiles.CleanEnvironment(start);
        start.EnvironmentVariables["TEMP"] = runtime; start.EnvironmentVariables["TMP"] = runtime;
        start.EnvironmentVariables["CHATGPTNX_RUNTIME_ROOT"] = runtime;
        return Process.Start(start);
    }

    private static Dictionary<string, object> Ack(string path, string ackToken, string ackVersion, Process child)
    {
        var deadline = DateTime.UtcNow.AddMilliseconds(WaitStartMs);
        while (DateTime.UtcNow < deadline)
        {
            if (child == null || child.HasExited) return null;
            if (File.Exists(path))
            {
                try
                {
                    var value = UpdateFiles.Read(path);
                    object ready;
                    var pid = UpdateFiles.Num(value, "pid");
                    var launcherPid = UpdateFiles.Num(value, "launcher_pid", false);
                    if (value.TryGetValue("ready", out ready) && ready is bool && (bool)ready
                            && UpdateFiles.Str(value, "token") == ackToken && UpdateFiles.Str(value, "version") == ackVersion
                            && (launcherPid == 0 || launcherPid == child.Id))
                    {
                        using (var worker = FindParent(pid)) if (worker != null && !worker.HasExited) return value;
                    }
                }
                catch { }
            }
            Thread.Sleep(100);
        }
        return null;
    }

    private static void Stop(Process child)
    {
        if (child == null || child.HasExited) return;
        var taskkill = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Windows), "System32", "taskkill.exe");
        using (var killer = Process.Start(new ProcessStartInfo {
            FileName = taskkill, Arguments = "/PID " + child.Id + " /T /F", UseShellExecute = false,
            CreateNoWindow = true, WindowStyle = ProcessWindowStyle.Hidden }))
        { if (!killer.WaitForExit(10000)) throw new IOException("stop_tree_timeout"); }
        if (!child.WaitForExit(10000)) throw new IOException("candidate_still_running");
    }

    private static void Replace(string source, string destination, string backup)
    {
        UpdateFiles.Plain(source); UpdateFiles.Plain(destination); UpdateFiles.Plain(backup);
        if (File.Exists(backup)) throw new IOException("backup_exists");
        var deadline = DateTime.UtcNow.AddSeconds(12);
        do
        {
            try { File.Replace(source, destination, backup, true); return; }
            catch (IOException) { if (DateTime.UtcNow >= deadline) throw; Thread.Sleep(200); }
        } while (true);
    }

    private static void Collect(Dictionary<string, object> ack)
    {
        // The current previous.exe is the one retained successful-update backup.
        // Failed/recovery/legacy/unrecognized batches are never collected.
        var updates = Path.GetDirectoryName(batch);
        var allowed = new HashSet<string>(StringComparer.OrdinalIgnoreCase) {
            "plan.json", "result.json", "prepared.json", "started.json", "previous.exe", "ChatGPTnx.Update.exe", "runtime-candidate"
        };
        foreach (var old in Directory.GetDirectories(updates))
        {
            try
            {
                if (UpdateFiles.Same(old, batch) || !Regex.IsMatch(Path.GetFileName(old), "^[a-f0-9]{32}$")) continue;
                UpdateFiles.Plain(old);
                var result = UpdateFiles.Read(Path.Combine(old, "result.json"));
                var oldPlan = UpdateFiles.Read(Path.Combine(old, "plan.json"));
                if (UpdateFiles.Num(result, "schema", false) != 2 || UpdateFiles.Str(result, "status") != "complete"
                        || !UpdateFiles.Same(UpdateFiles.Str(oldPlan, "root"), root)
                        || !UpdateFiles.Same(UpdateFiles.Str(oldPlan, "executable"), target)
                        || Directory.GetFileSystemEntries(old).Any(p => !allowed.Contains(Path.GetFileName(p)))) continue;
                UpdateFiles.RemoveTree(updates, old);
            }
            catch { /* A locked file is retried by the next successful update. */ }
        }
        var payloadId = UpdateFiles.Str(ack, "payload_id", false);
        var keep = new HashSet<string>(StringComparer.OrdinalIgnoreCase) {
            payloadId, UpdateFiles.Str(plan, "previous_payload_id", false)
        };
        var caches = UpdateFiles.Child(UpdateFiles.Child(root, "_wip"), "runtime");
        if (!Directory.Exists(caches) || payloadId == "") return;
        foreach (var cache in Directory.GetDirectories(caches))
        {
            try
            {
                var id = Path.GetFileName(cache);
                if (keep.Contains(id) || !Regex.IsMatch(id, @"^\d+\.\d+(?:\.\d+)?-[a-f0-9]{16}$")) continue;
                var owner = UpdateFiles.Read(UpdateFiles.Child(cache, "owner.json"));
                if (UpdateFiles.Num(owner, "schema") != 1 || UpdateFiles.Str(owner, "payload_id") != id) continue;
                var known = new HashSet<string> { "owner.json", "ChatGPTnx.Core.exe", "CORE-MANIFEST.json", "_internal", "temp" };
                if (Directory.GetFileSystemEntries(cache).Any(p => !known.Contains(Path.GetFileName(p)))) continue;
                UpdateFiles.RemoveTree(caches, cache);
            }
            catch { }
        }
    }

    private static int Run(string[] args)
    {
        if (args.Length != 2 || args[0] != "-Plan") return 1;
        var planPath = UpdateFiles.Full(args[1]);
        batch = UpdateFiles.Full(Path.GetDirectoryName(planPath));
        var replaced = false;
        var phase = "prepare";
        Process candidate = null;
        Mutex updateLock = null;
        bool ownsLock = false;
        try
        {
            if (Path.GetFileName(planPath) != "plan.json" || !Regex.IsMatch(Path.GetFileName(batch), "^[a-f0-9]{32}$"))
                throw new InvalidDataException("unsafe_plan");
            plan = UpdateFiles.Read(planPath);
            root = UpdateFiles.Full(UpdateFiles.Str(plan, "root"));
            target = UpdateFiles.Full(UpdateFiles.Str(plan, "executable"));
            var updates = UpdateFiles.Child(UpdateFiles.Child(root, "_wip"), "update");
            if (!UpdateFiles.Same(Path.GetDirectoryName(batch), updates)
                    || !UpdateFiles.Same(Path.GetDirectoryName(target), root) || !target.EndsWith(".exe", StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("unsafe_plan");
            UpdateFiles.Plain(target);
            token = UpdateFiles.Str(plan, "token"); version = UpdateFiles.Str(plan, "version");
            previousVersion = UpdateFiles.Str(plan, "previous_version"); previousSha = UpdateFiles.Str(plan, "previous_sha256");
            previousSize = UpdateFiles.Num(plan, "previous_size");
            if (UpdateFiles.Num(plan, "schema") != 2 || !Regex.IsMatch(token, "^[a-f0-9]{32}$")
                    || !Regex.IsMatch(version, @"^\d{1,5}\.\d{1,5}(?:\.\d{1,5})?$")
                    || !Regex.IsMatch(previousVersion, @"^\d{1,5}\.\d{1,5}(?:\.\d{1,5})?$")) throw new InvalidDataException("unsafe_plan");
            updateLock = new Mutex(false, @"Local\ChatGPTnx.Update." + UpdateFiles.TextDigest(root.ToUpperInvariant()));
            try { ownsLock = updateLock.WaitOne(0); } catch (AbandonedMutexException) { ownsLock = true; }
            if (!ownsLock) throw new IOException("another_update_running");
            var stage = UpdateFiles.Child(batch, "ChatGPTnx.new.exe");
            var backup = UpdateFiles.Child(batch, "previous.exe");
            if (File.Exists(backup) || File.Exists(UpdateFiles.Child(batch, "started.json"))) throw new IOException("transaction_already_used");
            Verify(stage, UpdateFiles.Num(plan, "size"), UpdateFiles.Str(plan, "sha256"));
            Verify(target, previousSize, previousSha);
            using (var parent = FindParent(UpdateFiles.Num(plan, "parent_pid")))
            using (var worker = FindParent(UpdateFiles.Num(plan, "worker_pid")))
            {
                UpdateFiles.Write(UpdateFiles.Child(batch, "prepared.json"), new Dictionary<string, object> {
                    { "ready", true }, { "token", token }, { "pid", Process.GetCurrentProcess().Id }
                });
                phase = "wait-parent";
                if ((parent != null && !parent.WaitForExit(WaitParentMs)) || (worker != null && !worker.WaitForExit(WaitParentMs)))
                    throw new TimeoutException("parent_still_running");
            }
            Verify(target, previousSize, previousSha);
            Verify(stage, UpdateFiles.Num(plan, "size"), UpdateFiles.Str(plan, "sha256"));
            phase = "replace"; Replace(stage, target, backup); replaced = true;
            phase = "start";
            candidate = StartApp(UpdateFiles.Child(batch, "runtime-candidate"), UpdateFiles.Child(batch, "started.json"), token);
            var ack = Ack(UpdateFiles.Child(batch, "started.json"), token, version, candidate);
            if (ack == null) throw new InvalidDataException("startup_failed");
            Result("complete", phase, "");
            try { Collect(ack); } catch { /* Cleanup cannot undo a healthy update. */ }
            return 0;
        }
        catch (Exception error)
        {
            if (!replaced) { Result("failed", phase, error.GetType().Name); return 1; }
            phase = "rollback";
            try
            {
                Stop(candidate);
                UpdateFiles.RemoveTree(batch, UpdateFiles.Child(batch, "runtime-candidate"));
                var backup = UpdateFiles.Child(batch, "previous.exe"); Verify(backup, previousSize, previousSha);
                Replace(backup, target, UpdateFiles.Child(batch, "failed.exe"));
                // A fresh journal and token also work with the previous 1.3.1
                // contract. Never mutate or reuse the candidate acknowledgement.
                var recovery = UpdateFiles.DirectoryChild(Path.GetDirectoryName(batch), Guid.NewGuid().ToString("N"));
                var recoveryToken = Guid.NewGuid().ToString("N");
                UpdateFiles.Write(UpdateFiles.Child(recovery, "plan.json"), new Dictionary<string, object> {
                    { "schema", 2 }, { "role", "recovery" }, { "origin", batch }, { "root", root }, { "executable", target },
                    { "token", recoveryToken }, { "version", previousVersion }, { "sha256", previousSha }, { "size", previousSize }
                });
                var restored = StartApp(UpdateFiles.Child(recovery, "runtime-rollback"), UpdateFiles.Child(recovery, "started.json"), recoveryToken);
                if (Ack(UpdateFiles.Child(recovery, "started.json"), recoveryToken, previousVersion, restored) == null)
                { Stop(restored); Result("recovery_needed", phase, "rollback_start_failed", recovery); return 3; }
                Result("rolled_back", phase, "startup_failed", recovery); return 2;
            }
            catch (Exception rollbackError) { Result("recovery_needed", phase, rollbackError.GetType().Name); return 3; }
        }
        finally
        {
            if (ownsLock) updateLock.ReleaseMutex();
            if (updateLock != null) updateLock.Dispose();
        }
    }

    public static int Main(string[] args) { UpdateFiles.ResetDllDirectory(); try { return Run(args); } catch { return 1; } }
}
