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
    private static string PayloadId { get { return PayloadVersion + "-" + PayloadSha256.Substring(0, 16); } }

    private static string Materialize(string root)
    {
        var work = UpdateFiles.DirectoryChild(root, "_wip");
        var caches = UpdateFiles.DirectoryChild(work, "runtime");
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

    private static Process StartCore(string core, string root, string launcher, string runtime, string[] args)
    {
        var forwarded = new List<string>(args);
        if (!args.Contains("--home") && String.IsNullOrEmpty(Environment.GetEnvironmentVariable("CHATGPTNX_HOME")))
        { forwarded.Add("--home"); forwarded.Add(root); }
        forwarded.Add("--launcher-executable"); forwarded.Add(launcher);
        forwarded.Add("--launcher-pid"); forwarded.Add(Process.GetCurrentProcess().Id.ToString());
        var start = new ProcessStartInfo {
            FileName = core, Arguments = String.Join(" ", forwarded.Select(UpdateFiles.Quote)),
            WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = true, WindowStyle = ProcessWindowStyle.Hidden
        };
        UpdateFiles.CleanEnvironment(start);
        start.EnvironmentVariables["CHATGPTNX_LAUNCHER_EXE"] = launcher;
        start.EnvironmentVariables["CHATGPTNX_LAUNCHER_PID"] = Process.GetCurrentProcess().Id.ToString();
        start.EnvironmentVariables["CHATGPTNX_PAYLOAD_ID"] = PayloadId;
        start.EnvironmentVariables["TEMP"] = runtime; start.EnvironmentVariables["TMP"] = runtime;
        return Process.Start(start);
    }

    public static int Main(string[] args)
    {
        UpdateFiles.ResetDllDirectory();
        string runtime = null, runtimeOwner = null;
        try
        {
            var launcher = UpdateFiles.Full(typeof(ChatGPTnxLauncher).Assembly.Location);
            var root = Path.GetDirectoryName(launcher);
            UpdateFiles.Plain(launcher);
            var core = Materialize(root);
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
            using (var process = StartCore(core, root, launcher, runtime, args))
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
