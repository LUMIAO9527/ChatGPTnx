// Windows 10-compatible primitives shared by the launcher and update worker.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
using Microsoft.Win32.SafeHandles;

[assembly: System.Runtime.Versioning.TargetFramework(".NETFramework,Version=v4.6.2")]

internal static class UpdateFiles
{
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool SetDllDirectory(string path);

    [StructLayout(LayoutKind.Sequential)]
    private struct FileInformation
    {
        public uint Attributes;
        public uint CreationTimeLow, CreationTimeHigh;
        public uint LastAccessTimeLow, LastAccessTimeHigh;
        public uint LastWriteTimeLow, LastWriteTimeHigh;
        public uint VolumeSerial;
        public uint FileSizeHigh;
        public uint FileSizeLow;
        public uint Links;
        public uint FileIndexHigh;
        public uint FileIndexLow;
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool GetFileInformationByHandle(SafeFileHandle handle, out FileInformation information);

    internal static void ResetDllDirectory()
    {
        // Opt into the 4.6.2 path APIs before any System.IO call. A terminated
        // core can leave deeply nested files for the updater to remove.
        AppContext.SetSwitch("Switch.System.IO.UseLegacyPathHandling", false);
        AppContext.SetSwitch("Switch.System.IO.BlockLongPaths", false);
        SetDllDirectory(null);
    }

    internal static string Full(string path)
    {
        if (path.StartsWith(@"\\?\UNC\", StringComparison.OrdinalIgnoreCase)) path = @"\\" + path.Substring(8);
        else if (path.StartsWith(@"\\?\", StringComparison.OrdinalIgnoreCase)) path = path.Substring(4);
        var full = Path.GetFullPath(path);
        return full.Length == Path.GetPathRoot(full).Length ? full :
            full.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
    }

    internal static string Extended(string path)
    {
        var full = Full(path);
        return full.StartsWith(@"\\") ? @"\\?\UNC\" + full.Substring(2) : @"\\?\" + full;
    }

    internal static bool Same(string a, string b)
    {
        return String.Equals(Full(a), Full(b), StringComparison.OrdinalIgnoreCase);
    }

    /* One identity for one file, whatever spelling reached it: an 8.3 short
       name, a SUBST drive, a UNC alias and even a hard link all open the same
       volume/file-index pair. Null means the file cannot be opened; callers
       then fall back to the conservative normalized-path comparison. */
    internal static string FileIdentity(string path)
    {
        try
        {
            using (var stream = new FileStream(Extended(path), FileMode.Open, FileAccess.Read,
                                               FileShare.ReadWrite | FileShare.Delete))
            {
                FileInformation information;
                if (!GetFileInformationByHandle(stream.SafeFileHandle, out information)) return null;
                return information.VolumeSerial.ToString("x8") + ":"
                    + information.FileIndexHigh.ToString("x8") + information.FileIndexLow.ToString("x8");
            }
        }
        catch { return null; }
    }

    internal static void Plain(string path)
    {
        // Check ancestors too: a normal file inside a junction is not confined.
        var current = Full(path);
        while (!String.IsNullOrEmpty(current))
        {
            if ((File.Exists(Extended(current)) || Directory.Exists(Extended(current))) &&
                    (File.GetAttributes(Extended(current)) & FileAttributes.ReparsePoint) != 0)
                throw new IOException("redirected_path");
            if (current.Length == Path.GetPathRoot(current).Length) break;
            current = Path.GetDirectoryName(current);
        }
    }

    internal static string Child(string parent, string name)
    {
        var result = Full(Path.Combine(parent, name));
        if (!Same(Path.GetDirectoryName(result), parent)) throw new IOException("unsafe_child");
        Plain(result);
        return result;
    }

    internal static string DirectoryChild(string parent, string name)
    {
        var path = Child(parent, name);
        Directory.CreateDirectory(Extended(path));
        Plain(path);
        return path;
    }

    internal static string Digest(string path)
    {
        Plain(path);
        using (var sha = SHA256.Create())
        using (var stream = File.OpenRead(Extended(path)))
            return BitConverter.ToString(sha.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();
    }

    internal static string TextDigest(string value)
    {
        using (var sha = SHA256.Create())
            return BitConverter.ToString(sha.ComputeHash(Encoding.UTF8.GetBytes(value))).Replace("-", "");
    }

    internal static string Quote(string value)
    {
        // CommandLineToArgvW rules, including trailing backslashes and quotes.
        var output = new StringBuilder("\"");
        var slashes = 0;
        foreach (var c in value)
        {
            if (c == '\\') { slashes++; continue; }
            output.Append('\\', c == '"' ? slashes * 2 + 1 : slashes);
            output.Append(c); slashes = 0;
        }
        output.Append('\\', slashes * 2); output.Append('"');
        return output.ToString();
    }

    internal static Dictionary<string, object> Read(string path)
    {
        Plain(path);
        if (new FileInfo(Extended(path)).Length > 65536) throw new InvalidDataException("oversized_journal");
        var value = new JavaScriptSerializer().DeserializeObject(File.ReadAllText(Extended(path), Encoding.UTF8)) as Dictionary<string, object>;
        if (value == null) throw new InvalidDataException("invalid_journal");
        return value;
    }

    internal static string Str(Dictionary<string, object> value, string key, bool required = true)
    {
        object item;
        if (value.TryGetValue(key, out item) && item is string && !String.IsNullOrEmpty((string)item)) return (string)item;
        if (required) throw new InvalidDataException("missing_" + key);
        return "";
    }

    internal static long Num(Dictionary<string, object> value, string key, bool required = true)
    {
        object item;
        if (value.TryGetValue(key, out item) && (item is int || item is long)) return Convert.ToInt64(item);
        if (required) throw new InvalidDataException("missing_" + key);
        return 0;
    }

    internal static void Write(string path, Dictionary<string, object> value)
    {
        Plain(path);
        var temp = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        using (var stream = new FileStream(Extended(temp), FileMode.CreateNew, FileAccess.Write, FileShare.None))
        {
            var bytes = Encoding.UTF8.GetBytes(new JavaScriptSerializer().Serialize(value));
            stream.Write(bytes, 0, bytes.Length); stream.Flush(true);
        }
        if (File.Exists(Extended(path))) File.Replace(Extended(temp), Extended(path), null, true);
        else File.Move(Extended(temp), Extended(path));
    }

    internal static void CleanEnvironment(ProcessStartInfo start)
    {
        var remove = new List<string>();
        string oldRuntime = start.EnvironmentVariables["_PYI_APPLICATION_HOME_DIR"] ?? start.EnvironmentVariables["_MEIPASS2"];
        foreach (var key in start.EnvironmentVariables.Keys)
        {
            var name = (string)key;
            if (name.StartsWith("_PYI_", StringComparison.OrdinalIgnoreCase)
                    || name.Equals("_MEIPASS2", StringComparison.OrdinalIgnoreCase)
                    || name.Equals("PYINSTALLER_RESET_ENVIRONMENT", StringComparison.OrdinalIgnoreCase)) remove.Add(name);
        }
        foreach (var name in remove) start.EnvironmentVariables.Remove(name);
        if (!String.IsNullOrEmpty(oldRuntime))
        {
            var parts = (start.EnvironmentVariables["PATH"] ?? "").Split(';');
            start.EnvironmentVariables["PATH"] = String.Join(";", Array.FindAll(parts,
                p => !p.Trim('"').StartsWith(oldRuntime, StringComparison.OrdinalIgnoreCase)));
        }
        start.EnvironmentVariables["PYINSTALLER_RESET_ENVIRONMENT"] = "1";
    }

    private static void CheckTree(string path)
    {
        Plain(path);
        foreach (var child in Directory.GetFileSystemEntries(Extended(path)))
        { Plain(child); if (Directory.Exists(Extended(child))) CheckTree(child); }
    }

    internal static bool RemoveTree(string owner, string path)
    {
        var prefix = Full(owner) + Path.DirectorySeparatorChar;
        if (!Full(path).StartsWith(prefix, StringComparison.OrdinalIgnoreCase)) throw new IOException("cleanup_outside_owner");
        if (!Directory.Exists(Extended(path))) return true;
        CheckTree(path);
        // Explicit extended syntax also covers machines whose Win32 long-path
        // policy is disabled. The owner boundary was checked before prefixing.
        var extended = Extended(path);
        var deadline = DateTime.UtcNow.AddSeconds(5);
        do
        {
            try { Directory.Delete(extended, true); return true; }
            catch (IOException) { Thread.Sleep(150); }
            catch (UnauthorizedAccessException) { Thread.Sleep(150); }
        } while (DateTime.UtcNow < deadline);
        return false;
    }
}
