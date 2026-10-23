// The public EXE is a native launcher; Python runs in an independently owned core.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Reflection;
using System.Threading;
using System.Windows.Forms;

[assembly: AssemblyTitle("ChatGPTnx")]
[assembly: AssemblyProduct("ChatGPTnx")]
[assembly: AssemblyVersion("__FILE_VERSION__")]
[assembly: AssemblyFileVersion("__FILE_VERSION__")]
[assembly: AssemblyInformationalVersion("__PAYLOAD_VERSION__")]

internal static class ChatGPTnxLauncher
{
    private const string PayloadName = "ChatGPTnx.Core.zip";
    private const string PayloadVersion = "__PAYLOAD_VERSION__";
    private const string PayloadSha256 = "__PAYLOAD_SHA256__";
    private const string ManifestSha256 = "__MANIFEST_SHA256__";
    private const string LocationMarker = ".chatgptnx-location";
    private static string PayloadId { get { return PayloadVersion + "-" + PayloadSha256.Substring(0, 16); } }

    private static string Materialize(string cacheRoot)
    {
        var caches = cacheRoot;
        var directory = UpdateFiles.Child(caches, PayloadId);
        var target = UpdateFiles.Child(directory, "ChatGPTnx.Core.exe");
        using (var cacheLock = new Mutex(false, @"Local\ChatGPTnx.Core." + UpdateFiles.TextDigest(directory.ToUpperInvariant())))
        {
            bool ownsLock;
            try { ownsLock = cacheLock.WaitOne(15000); } catch (AbandonedMutexException) { ownsLock = true; }
            if (!ownsLock) throw new IOException("core_cache_busy");
            try
            {
                if (Directory.Exists(directory))
                {
                    VerifyCore(directory);
                }
                else
                {
                    var staging = UpdateFiles.DirectoryChild(caches, ".install-" + Guid.NewGuid().ToString("N"));
                    try
                    {
                        using (var input = typeof(ChatGPTnxLauncher).Assembly.GetManifestResourceStream(PayloadName))
                        using (var archive = new ZipArchive(input, ZipArchiveMode.Read))
                        {
                            foreach (var entry in archive.Entries)
                            {
                                var name = entry.FullName.Replace('/', Path.DirectorySeparatorChar);
                                var path = SafePayloadPath(staging, name);
                                Directory.CreateDirectory(UpdateFiles.Extended(Path.GetDirectoryName(path)));
                                using (var source = entry.Open())
                                using (var output = new FileStream(UpdateFiles.Extended(path), FileMode.CreateNew, FileAccess.Write, FileShare.None))
                                { source.CopyTo(output); output.Flush(true); }
                            }
                        }
                        VerifyCore(staging);
                        UpdateFiles.Write(UpdateFiles.Child(staging, "owner.json"), new Dictionary<string, object> {
                            { "schema", 1 }, { "payload_id", PayloadId }, { "payload_sha256", PayloadSha256 }
                        });
                        Directory.Move(UpdateFiles.Extended(staging), UpdateFiles.Extended(directory));
                    }
                    finally { if (Directory.Exists(staging)) UpdateFiles.RemoveTree(caches, staging); }
                }
            }
            finally { cacheLock.ReleaseMutex(); }
        }
        return target;
    }

    private static string SafePayloadPath(string directory, string name)
    {
        if (Path.IsPathRooted(name) || name.Contains(":")) throw new InvalidDataException("unsafe_payload_path");
        var path = UpdateFiles.Full(Path.Combine(directory, name.Replace('/', Path.DirectorySeparatorChar)));
        if (!path.StartsWith(UpdateFiles.Full(directory) + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("unsafe_payload_path");
        UpdateFiles.Plain(path);
        return path;
    }

    private static void VerifyCore(string directory)
    {
        var manifest = UpdateFiles.Child(directory, "CORE-MANIFEST.json");
        if (UpdateFiles.Digest(manifest) != ManifestSha256) throw new InvalidDataException("core_manifest_changed");
        var entries = (object[])UpdateFiles.Read(manifest)["files"];
        foreach (Dictionary<string, object> entry in entries)
        {
            var path = SafePayloadPath(directory, UpdateFiles.Str(entry, "path"));
            if (!File.Exists(UpdateFiles.Extended(path)) || new FileInfo(UpdateFiles.Extended(path)).Length != UpdateFiles.Num(entry, "size")
                    || UpdateFiles.Digest(path) != UpdateFiles.Str(entry, "sha256"))
                throw new InvalidDataException("core_checksum_failed");
        }
    }

    /* A marker is a confirmed location only when it is readable and any redirect
       it records still resolves to an installed launcher. A stale or corrupt
       marker must re-enter the folder choice: running normally beside the
       downloaded EXE would write _wip/_data there after the app promised not to. */
    private sealed class LocationState
    {
        public bool Exists;
        public bool Broken;
        public string Redirect;
    }

    private static LocationState ReadLocationState(string root)
    {
        var state = new LocationState();
        var marker = UpdateFiles.Child(root, LocationMarker);
        if (!File.Exists(UpdateFiles.Extended(marker))) return state;
        state.Exists = true;
        try
        {
            var document = UpdateFiles.Read(marker);
            object value;
            if (!document.TryGetValue("moved_to", out value)) return state; // plain install marker
            var targetText = value as string;
            if (String.IsNullOrEmpty(targetText)) { state.Broken = true; return state; }
            var target = UpdateFiles.Full(targetText);
            if (!Path.IsPathRooted(target)) { state.Broken = true; return state; }
            var executable = UpdateFiles.Child(target, "ChatGPTnx.exe");
            var loops = UpdateFiles.Same(target, root);
            if (!loops && File.Exists(UpdateFiles.Extended(executable)))
            {
                // File identity, not spelling: an 8.3 name, a SUBST drive or a
                // UNC alias can reach this same launcher, and redirecting to it
                // would start the downloaded copy again forever.
                var running = UpdateFiles.FileIdentity(UpdateFiles.Full(
                    typeof(ChatGPTnxLauncher).Assembly.Location));
                var destination = UpdateFiles.FileIdentity(executable);
                loops = running != null && destination != null
                    && String.Equals(running, destination, StringComparison.OrdinalIgnoreCase);
            }
            if (loops) { state.Broken = true; return state; } // self-redirect loop
            if (File.Exists(UpdateFiles.Extended(executable))) state.Redirect = executable;
            else state.Broken = true; // redirect target was moved or deleted
        }
        catch { state.Broken = true; } // unreadable/corrupt marker is never trusted
        return state;
    }

    /* Modes that own their data root and are never a user-facing portable
       install: build acceptance, update acknowledgement and diagnostics.
       --once and --home deliberately stay out of this list. On a fresh folder
       they must not write _wip/_data beside the download before the location is
       chosen; --once reports that setup is required on stderr and --home
       proceeds through setup. */
    private static bool IsInternalMode(string[] args)
    {
        foreach (var flag in new[] { "--update-ack", "--runtime-check-report",
                                     "--acceptance-relay", "--locate-task" })
            if (args.Contains(flag)) return true;
        return false;
    }

    /* The GUI path tells the user with a dialog because a winexe has no
       console. A scripted --once call must never block on a dialog nobody can
       see: it reports the same one-line diagnostic on stderr and exits 1. */
    private static int ShowSetupRequired(string message, bool once)
    {
        if (once)
        {
            try { Console.Error.WriteLine(message); } catch { }
            return 1;
        }
        try { MessageBox.Show(message, "ChatGPTnx", MessageBoxButtons.OK, MessageBoxIcon.Information); } catch { }
        return 1;
    }

    private static Process StartCore(string core, string home, string workingDirectory, string launcher,
                                     string runtime, string[] args, bool show = false)
    {
        var forwarded = new List<string>(args);
        if (!forwarded.Contains("--home") && String.IsNullOrEmpty(Environment.GetEnvironmentVariable("CHATGPTNX_HOME")))
        { forwarded.Add("--home"); forwarded.Add(home); }
        forwarded.Add("--launcher-executable"); forwarded.Add(launcher);
        forwarded.Add("--launcher-pid"); forwarded.Add(Process.GetCurrentProcess().Id.ToString());
        var start = new ProcessStartInfo {
            FileName = core, Arguments = String.Join(" ", forwarded.Select(UpdateFiles.Quote)),
            WorkingDirectory = workingDirectory, UseShellExecute = false, CreateNoWindow = true,
            WindowStyle = ProcessWindowStyle.Hidden
        };
        UpdateFiles.CleanEnvironment(start);
        start.EnvironmentVariables["CHATGPTNX_LAUNCHER_EXE"] = launcher;
        start.EnvironmentVariables["CHATGPTNX_LAUNCHER_PID"] = Process.GetCurrentProcess().Id.ToString();
        start.EnvironmentVariables["CHATGPTNX_PAYLOAD_ID"] = PayloadId;
        // The real host temp, so a restarted process never inherits a private
        // bootstrap temp directory that its parent is about to delete.
        start.EnvironmentVariables["CHATGPTNX_HOST_TEMP"] = Path.GetTempPath();
        start.EnvironmentVariables["TEMP"] = runtime; start.EnvironmentVariables["TMP"] = runtime;
        if (show) start.EnvironmentVariables["CHATGPTNX_SHOW"] = "1";
        return Process.Start(start);
    }

    /* Bootstrap trees left behind by a crashed/killed launcher would otherwise
       accumulate under %TEMP%. Only our GUID-named runs older than a day are
       removed; a concurrent first run is always fresh and is never touched. */
    private static void CleanupStaleSetups(string owner)
    {
        try
        {
            foreach (var path in Directory.GetDirectories(UpdateFiles.Extended(owner)))
            {
                var name = Path.GetFileName(path);
                if (name.Length != 32 || !name.All(Uri.IsHexDigit)) continue;
                try
                {
                    if (Directory.GetLastWriteTimeUtc(UpdateFiles.Extended(path)) > DateTime.UtcNow.AddDays(-1))
                        continue;
                    UpdateFiles.RemoveTree(owner, UpdateFiles.Full(path));
                }
                catch { }
            }
        }
        catch { }
    }

    private static int RunLocationSetup(string root, string launcher, string[] args)
    {
        var owner = UpdateFiles.DirectoryChild(Path.GetTempPath(), "ChatGPTnx-Setup");
        CleanupStaleSetups(owner);
        var run = UpdateFiles.DirectoryChild(owner, Guid.NewGuid().ToString("N"));
        try
        {
            var cache = UpdateFiles.DirectoryChild(run, "runtime");
            var home = UpdateFiles.DirectoryChild(run, "home");
            var temp = UpdateFiles.DirectoryChild(run, "temp");
            var core = Materialize(cache);
            var forwarded = new List<string>(args) {
                "--location-setup", "--location-root", root, "--home", home
            };
            using (var process = StartCore(core, home, run, launcher, temp, forwarded.ToArray(), true))
            {
                process.WaitForExit();
                return process.ExitCode;
            }
        }
        finally
        {
            try { UpdateFiles.RemoveTree(owner, run); } catch { }
        }
    }

    private static void StartRedirect(string executable, string[] args)
    {
        var start = new ProcessStartInfo {
            FileName = executable,
            Arguments = String.Join(" ", args.Select(UpdateFiles.Quote)),
            WorkingDirectory = Path.GetDirectoryName(executable), UseShellExecute = false
        };
        start.EnvironmentVariables["CHATGPTNX_SHOW"] = "1";
        Process.Start(start);
    }

    [STAThread]
    public static int Main(string[] args)
    {
        UpdateFiles.ResetDllDirectory();
        string runtime = null, runtimeOwner = null;
        try
        {
            var launcher = UpdateFiles.Full(typeof(ChatGPTnxLauncher).Assembly.Location);
            var root = Path.GetDirectoryName(launcher);
            UpdateFiles.Plain(launcher);
            var location = ReadLocationState(root);
            if (!String.IsNullOrEmpty(location.Redirect))
            {
                StartRedirect(location.Redirect, args);
                return 0;
            }
            var initialized = location.Exists
                || Directory.Exists(UpdateFiles.Extended(UpdateFiles.Child(root, "_data")))
                || File.Exists(UpdateFiles.Extended(UpdateFiles.Child(root, "accounts.txt")));
            if (!IsInternalMode(args) && (location.Broken || !initialized))
            {
                if (args.Contains("--once"))
                {
                    return ShowSetupRequired(location.Broken
                        ? "ChatGPTnx 的位置设置不完整，请重新打开程序完成设置。"
                        : "请先完成首次设置：重新打开 ChatGPTnx 并选择程序文件夹。", true);
                }
                return RunLocationSetup(root, launcher, args);
            }
            var cache = UpdateFiles.DirectoryChild(UpdateFiles.DirectoryChild(root, "_wip"), "runtime");
            var core = Materialize(cache);
            var requestedRuntime = Environment.GetEnvironmentVariable("CHATGPTNX_RUNTIME_ROOT");
            if (!String.IsNullOrEmpty(requestedRuntime))
            {
                var updates = UpdateFiles.Child(UpdateFiles.Child(root, "_wip"), "update");
                var transaction = Path.GetDirectoryName(UpdateFiles.Full(requestedRuntime));
                var name = Path.GetFileName(requestedRuntime);
                if (!UpdateFiles.Same(Path.GetDirectoryName(transaction), updates)
                        || (name != "runtime-candidate" && name != "runtime-rollback")) throw new IOException("unsafe_runtime");
                runtimeOwner = UpdateFiles.DirectoryChild(transaction, name);
            }
            else runtimeOwner = UpdateFiles.DirectoryChild(UpdateFiles.DirectoryChild(root, "_wip"), "run");
            runtime = UpdateFiles.DirectoryChild(runtimeOwner, Guid.NewGuid().ToString("N"));
            using (var process = StartCore(core, root, root, launcher, runtime, args))
            { process.WaitForExit(); return process.ExitCode; }
        }
        catch (Exception error)
        {
            var check = Array.IndexOf(args, "--runtime-check-report");
            if (check >= 0 && check + 1 < args.Length)
            {
                try
                {
                    var report = UpdateFiles.Full(args[check + 1]);
                    var root = Path.GetDirectoryName(UpdateFiles.Full(typeof(ChatGPTnxLauncher).Assembly.Location));
                    var prefix = UpdateFiles.Child(root, "_wip") + Path.DirectorySeparatorChar;
                    if (report.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
                        UpdateFiles.Write(report, new Dictionary<string, object> {
                            { "version", PayloadVersion }, { "dependencies_ready", false },
                            { "error_type", error.GetType().Name }, { "error", error.ToString() }
                        });
                }
                catch { }
                return 1;
            }
            try { MessageBox.Show("ChatGPTnx 启动失败：" + error.GetType().Name, "ChatGPTnx", MessageBoxButtons.OK, MessageBoxIcon.Error); } catch { }
            return 1;
        }
        finally
        {
            if (runtime != null) { try { UpdateFiles.RemoveTree(runtimeOwner, runtime); } catch { } }
        }
    }
}