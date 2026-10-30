using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;

// HivisionIDPhotos 启动器
//
// 作用：把「程序所在目录」转换成 Windows 8.3 短路径，再用短路径启动真正的
//       HivisionIDPhotos.real.exe，从根上规避 MAX_PATH(260) 限制。
//
// 为什么必须在外层做：路径过长时，PyInstaller 引导程序在加载 python311.dll /
// base_library.zip 阶段就已失败，Python 层任何代码（含 runtime hook）都来不及执行。
//
// 编译（Windows 自带 .NET Framework 4.x 的 csc 即可，无需安装任何 SDK）：
//   C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe /nologo /target:winexe ^
//       /optimize+ /out:Launcher.exe /r:System.Windows.Forms.dll Launcher.cs

internal static class Launcher
{
    private const string TargetName = "HivisionIDPhotos.real.exe";
    private const string LegacyName = "HivisionIDPhotos.exe";

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern uint GetShortPathNameW(string longPath, StringBuilder shortPath, uint bufferLength);

    private static string Short(string path)
    {
        if (string.IsNullOrEmpty(path)) return null;
        foreach (uint size in new uint[] { 512, 4096, 32768 })
        {
            StringBuilder sb = new StringBuilder((int)size);
            uint n = GetShortPathNameW(path, sb, size);
            if (n > 0 && n < size) return sb.ToString();
        }
        return null;
    }

    [STAThread]
    private static int Main(string[] args)
    {
        string dir;
        try
        {
            dir = Path.GetDirectoryName(Application.ExecutablePath);
        }
        catch (Exception)
        {
            dir = Environment.CurrentDirectory;
        }
        if (string.IsNullOrEmpty(dir)) dir = Environment.CurrentDirectory;

        string target = Path.Combine(dir, TargetName);
        if (!File.Exists(target))
        {
            // 兼容未改名的旧结构
            target = Path.Combine(dir, LegacyName);
            if (!File.Exists(target))
            {
                MessageBox.Show("启动器所在目录中找不到主程序，请重新解压完整的发行包。",
                    "HivisionIDPhotos", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return 2;
            }
        }

        string runDir = dir;
        string shortDir = Short(dir);
        if (!string.IsNullOrEmpty(shortDir) && shortDir.Length < dir.Length + 1)
        {
            runDir = shortDir;
        }

        string runExe = Path.Combine(runDir, Path.GetFileName(target));
        try
        {
            ProcessStartInfo psi = new ProcessStartInfo(runExe);
            psi.WorkingDirectory = runDir;
            psi.UseShellExecute = false;
            if (!string.Equals(runDir, dir, StringComparison.OrdinalIgnoreCase))
            {
                // 让程序界面/日志能显示用户实际解压的长路径
                psi.EnvironmentVariables["HV_ORIG_HOME"] = dir;
            }
            string rest = string.Join(" ", args);
            if (!string.IsNullOrEmpty(rest)) psi.Arguments = rest;
            Process.Start(psi);
            return 0;
        }
        catch (Exception ex)
        {
            MessageBox.Show(
                "启动失败：" + ex.Message + "\r\n\r\n" +
                "该目录路径可能过长。请把整个文件夹解压到较短的英文路径后重试，\r\n" +
                "例如：D:\\HivisionIDPhotos",
                "HivisionIDPhotos", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }
}
