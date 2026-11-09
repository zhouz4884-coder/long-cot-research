// Quiet native extraction of one pinned ProofWidgets archive for a scoped Lake process.
using System;
using System.Diagnostics;
using System.IO;
using System.Security.Cryptography;

public static class ProofWidgetsTar
{
    private const string ArchiveSha256 = "4e9bda0d02f8a8812bbd4416c6ded6fdf3c43c70c0caabdf3179fbee691ad469";

    private static bool SamePath(string first, string second)
    {
        return String.Equals(Path.GetFullPath(first), Path.GetFullPath(second), StringComparison.OrdinalIgnoreCase);
    }

    private static int Fail(string message)
    {
        Console.Error.WriteLine(message);
        return 64;
    }

    public static int Main(string[] args)
    {
        string root = Environment.GetEnvironmentVariable("D38_PROOFWIDGETS_ROOT");
        if (String.IsNullOrEmpty(root) || args.Length != 5 || args[0] != "-xvvz" || args[1] != "-f" || args[3] != "-C")
            return Fail("Quiet tar permits only the pinned ProofWidgets extraction.");

        string archive = Path.GetFullPath(Path.Combine(root, "ProofWidgets4.tar.gz"));
        string target = Path.GetFullPath(Path.Combine(root, "build"));
        if (!SamePath(archive, args[2]) || !SamePath(target, args[4]) || !Directory.Exists(target) || !File.Exists(archive))
            return Fail("Quiet tar refused an unexpected input or output path.");

        using (SHA256 digest = SHA256.Create())
        using (FileStream input = File.OpenRead(archive))
        {
            string actual = BitConverter.ToString(digest.ComputeHash(input)).Replace("-", "").ToLowerInvariant();
            if (actual != ArchiveSha256)
                return Fail("Quiet tar refused an archive with a different SHA-256.");
        }

        var start = new ProcessStartInfo(Path.Combine(Environment.SystemDirectory, "tar.exe"),
                                        "-xz -f \"" + archive + "\" -C \"" + target + "\"");
        start.UseShellExecute = false;
        start.RedirectStandardError = true;
        using (Process process = Process.Start(start))
        {
            process.StandardError.ReadToEnd();
            process.WaitForExit();
            if (process.ExitCode != 0)
                Console.Error.WriteLine("Native tar failed with exit code " + process.ExitCode + ".");
            return process.ExitCode;
        }
    }
}
