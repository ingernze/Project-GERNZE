using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Threading;
using System.Windows.Forms;

// No network, credential access, content reads, Codex control or periodic timers.
namespace QuietCodex {
    sealed class ActivityWindow : Form {
        readonly Label folder = new Label(), status = new Label(), overview = new Label();
        readonly CheckBox showNames = new CheckBox();
        readonly Dictionary<string, DateTime> modified = new Dictionary<string, DateTime>(StringComparer.OrdinalIgnoreCase);
        readonly Color background = ColorTranslator.FromHtml("#161d31"), panel = ColorTranslator.FromHtml("#1e2841"),
            ink = ColorTranslator.FromHtml("#eeeaf3"), muted = ColorTranslator.FromHtml("#aaa8bf"),
            accent = ColorTranslator.FromHtml("#c4b7ed");
        readonly ListView list = new ListView();
        readonly object gate = new object();
        readonly HashSet<string> pending = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        readonly Dictionary<string, ListViewItem> rows = new Dictionary<string, ListViewItem>(StringComparer.OrdinalIgnoreCase);
        FileSystemWatcher watcher;
        string root;
        int posted;
        int generation;
        System.Diagnostics.Process owner;
        bool closing;

        public ActivityWindow(string initialRoot) {
            Text = "莉宝 · Codex 活动观察（只读元数据）";
            ClientSize = new Size(800, 530); MinimumSize = new Size(640, 440);
            Font = new Font("Microsoft YaHei UI", 10F);
            BackColor = background; ForeColor = ink;
            Padding = new Padding(20, 12, 20, 12);
            var heading = new Label { Text = "✦  活动观察", Dock = DockStyle.Top, Height = 42,
                Font = new Font("Microsoft YaHei UI", 18F), ForeColor = ink };
            var subtitle = new Label { Text = "看看本地日志最近有没有更新。", Dock = DockStyle.Top, Height = 28, ForeColor = muted };
            overview.Dock = DockStyle.Top; overview.Height = 74; overview.BackColor = panel;
            overview.Padding = new Padding(12, 10, 12, 8); overview.ForeColor = accent;
            overview.Text = "正在读取本地记录信息……";
            var top = new FlowLayoutPanel { Dock = DockStyle.Top, Height = 52, Padding = new Padding(0, 10, 0, 4),
                BackColor = background, WrapContents = false };
            AddButton(top, "选择目录", ChooseRoot);
            AddButton(top, "开始观察", delegate { StartWatch(); });
            AddButton(top, "停止观察", delegate { StopWatch("已停止观察，没有后台监测。"); });
            AddButton(top, "刷新记录", delegate { Snapshot(); });
            showNames.Text = "显示文件名"; showNames.AutoSize = true; showNames.Margin = new Padding(12, 7, 0, 0);
            showNames.ForeColor = muted; showNames.CheckedChanged += delegate { RefreshOverview(); };
            top.Controls.Add(showNames);
            folder.Dock = DockStyle.Top; folder.Height = 30; folder.Padding = new Padding(0, 3, 0, 0);
            folder.AutoEllipsis = true; folder.ForeColor = muted;
            status.Dock = DockStyle.Bottom; status.Height = 62; status.Padding = new Padding(0, 8, 0, 0);
            status.ForeColor = muted;
            list.Dock = DockStyle.Fill; list.View = View.Details; list.FullRowSelect = true;
            list.HideSelection = false; list.MultiSelect = false; list.BorderStyle = BorderStyle.None;
            list.BackColor = panel; list.ForeColor = ink; list.ShowItemToolTips = true; list.OwnerDraw = true;
            list.Columns.Add("本地记录", 310);
            list.Columns.Add("最近更新时间", 180);
            list.Columns.Add("文件大小", 100);
            list.DrawColumnHeader += delegate(object sender, DrawListViewColumnHeaderEventArgs e) {
                using (var brush = new SolidBrush(background)) e.Graphics.FillRectangle(brush, e.Bounds);
                TextRenderer.DrawText(e.Graphics, e.Header.Text, Font, e.Bounds, muted, TextFormatFlags.Left | TextFormatFlags.VerticalCenter);
            };
            list.DrawItem += delegate(object sender, DrawListViewItemEventArgs e) { e.DrawDefault = true; };
            list.DrawSubItem += delegate(object sender, DrawListViewSubItemEventArgs e) { e.DrawDefault = true; };
            Controls.Add(list); Controls.Add(folder); Controls.Add(top); Controls.Add(overview);
            Controls.Add(subtitle); Controls.Add(heading); Controls.Add(status);
            Shown += delegate { SetRoot(initialRoot); LayoutColumns(); };
            list.Resize += delegate { LayoutColumns(); };
            Resize += delegate {
                if (WindowState == FormWindowState.Minimized)
                    StopWatch("已最小化并停止观察。恢复窗口后可点“开始观察”。");
                LayoutColumns();
            };
        }
        [System.Runtime.InteropServices.DllImport("user32.dll")]
        static extern bool ShowScrollBar(IntPtr handle, int bar, bool show);
        void LayoutColumns() {
            if (list.Columns.Count == 3 && list.ClientSize.Width > 300)
                list.Columns[0].Width = Math.Max(180, list.ClientSize.Width - list.Columns[1].Width - list.Columns[2].Width - 4);
            // Columns fit; filenames remain available in tooltips, so no horizontal scroll is needed.
            if (list.IsHandleCreated) ShowScrollBar(list.Handle, 0, false);
        }
        void AddButton(FlowLayoutPanel p, string text, EventHandler action) {
            var b = new Button { Text = text, AutoSize = true, FlatStyle = FlatStyle.Flat,
                BackColor = panel, ForeColor = ink, Padding = new Padding(8, 3, 8, 3), Cursor = Cursors.Hand };
            b.FlatAppearance.BorderColor = ColorTranslator.FromHtml("#45465e");
            b.FlatAppearance.MouseOverBackColor = ColorTranslator.FromHtml("#303a58");
            b.FlatAppearance.MouseDownBackColor = ColorTranslator.FromHtml("#45465e");
            b.Click += action; p.Controls.Add(b);
        }
        static string SizeLabel(long bytes) {
            return bytes >= 1024L * 1024L ? (bytes / (1024.0 * 1024.0)).ToString("F1") + " MB"
                : (bytes / 1024.0).ToString("F1") + " KB";
        }
        void RefreshOverview() {
            DateTime latest = DateTime.MinValue;
            int todayCount = 0, index = 0;
            foreach (ListViewItem item in list.Items) {
                string path = (string)item.Tag;
                DateTime time = modified[path];
                index++;
                item.Text = showNames.Checked ? item.Name : (time.Date == DateTime.Today ? "今天更新的记录 " : "较早的记录 ") + index.ToString("00");
                if (time > latest) latest = time;
                if (time.Date == DateTime.Today) todayCount++;
            }
            overview.Text = "当前显示 " + list.Items.Count + " 份记录  ·  其中 " + todayCount + " 份今天更新"
                + "\n最近文件更新：" + (latest == DateTime.MinValue ? "暂未发现记录" : latest.ToString("yyyy-MM-dd HH:mm:ss"));
        }
        void ChooseRoot(object sender, EventArgs args) {
            using (var dialog = new FolderBrowserDialog()) {
                dialog.Description = "选择本机 Codex sessions 目录；不选择账号或配置文件。";
                if (dialog.ShowDialog(this) == DialogResult.OK) SetRoot(dialog.SelectedPath);
            }
        }
        bool SafePath(string path) {
            try {
                string full = Path.GetFullPath(path);
                if (full.StartsWith(@"\\") || !Path.IsPathRooted(full)) return false;
                if (new DriveInfo(Path.GetPathRoot(full)).DriveType == DriveType.Network) return false;
                // Reject junctions/symlinks at every existing path component.
                var components = new List<string>();
                for (string p = full; !String.IsNullOrEmpty(p); p = Path.GetDirectoryName(p)) components.Add(p);
                // Inspect ancestors first; do not traverse a linked parent.
                components.Reverse();
                foreach (string p in components)
                    if ((File.GetAttributes(p) & FileAttributes.ReparsePoint) != 0) return false;
                return true;
            } catch { return false; }
        }
        bool Eligible(string path) {
            try {
                string full = Path.GetFullPath(path), name = Path.GetFileName(full);
                return root != null && full.StartsWith(root + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)
                    && name.StartsWith("rollout-", StringComparison.OrdinalIgnoreCase)
                    && name.EndsWith(".jsonl", StringComparison.OrdinalIgnoreCase) && SafePath(full);
            } catch { return false; }
        }
        void SetRoot(string path) {
            StopWatch("正在选择目录。"); list.Items.Clear(); rows.Clear(); modified.Clear(); root = null; RefreshOverview();
            if (!SafePath(path) || !Directory.Exists(path)) {
                folder.Text = "目录不可用，请选择本机 sessions 目录（不支持网络路径、链接或联接目录）。";
                status.Text = "没有启动监测；未扫描其他目录。"; return;
            }
            string fullRoot = Path.GetFullPath(path);
            if (String.Equals(fullRoot, Path.GetPathRoot(fullRoot), StringComparison.OrdinalIgnoreCase)) {
                folder.Text = "请选择具体日志目录，不监测整个磁盘。";
                status.Text = "没有启动监测。"; return;
            }
            root = fullRoot.TrimEnd(Path.DirectorySeparatorChar);
            folder.Text = "观察目录：" + root;
            StartWatch(); Snapshot();
        }
        void StartWatch() {
            if (root == null || !SafePath(root)) { status.Text = "请先选择有效的本机目录。"; return; }
            StopWatch("正在启动观察。");
            try {
                watcher = new FileSystemWatcher(root, "rollout-*.jsonl");
                watcher.IncludeSubdirectories = true;
                watcher.NotifyFilter = NotifyFilters.FileName | NotifyFilters.LastWrite | NotifyFilters.Size;
                watcher.InternalBufferSize = 8192;
                int stamp = generation;
                watcher.Changed += delegate(object s, FileSystemEventArgs e) { Queue(e.FullPath, stamp); };
                watcher.Created += delegate(object s, FileSystemEventArgs e) { Queue(e.FullPath, stamp); };
                watcher.Renamed += delegate(object s, RenamedEventArgs e) { Queue(e.FullPath, stamp); };
                watcher.Error += delegate {
                    try { BeginInvoke((MethodInvoker)delegate { if (!closing && stamp == generation) StopWatch("目录事件丢失或监测出错：已停止。请检查目录后重新开始，不能据此判断任务状态。"); }); }
                    catch (InvalidOperationException) { }
                };
                watcher.EnableRaisingEvents = true;
                status.Text = "正在观察；尚未看到新的日志文件变化。\n文件更新只表示日志有变化；无法判断任务完成，也不显示账号剩余额度。";
            } catch { StopWatch("启动失败；没有后台监测。请重新选择有效目录。"); }
        }
        void Queue(string path, int stamp) {
            // Generation-bound callbacks cannot drain or stop a later watcher.
            lock (gate) {
                if (closing || stamp != generation || watcher == null) return;
                if (pending.Count < 64) pending.Add(path);
                if (posted != 0) return;
                posted = 1;
            }
            try { BeginInvoke((MethodInvoker)delegate { Drain(stamp); }); }
            catch (InvalidOperationException) { lock (gate) { if (stamp == generation) posted = 0; } }
        }
        void Drain(int stamp) {
            string[] paths;
            lock (gate) {
                if (closing || stamp != generation || watcher == null) return;
                paths = new string[pending.Count]; pending.CopyTo(paths);
                pending.Clear(); posted = 0;
            }
            bool seen = false;
            foreach (string p in paths) if (ShowMetadata(p)) seen = true;
            if (seen) status.Text = "刚刚观察到日志变化：" + DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss")
                + "\n文件变化不代表任务完成或结果正确。";
        }
        bool ShowMetadata(string path) {
            if (!Eligible(path)) return false;
            try {
                var info = new FileInfo(path); if (!info.Exists) return false;
                ListViewItem item;
                if (rows.TryGetValue(path, out item)) { list.Items.Remove(item); rows.Remove(path); modified.Remove(path); }
                while (list.Items.Count >= 20) {
                    var last = list.Items[list.Items.Count - 1]; rows.Remove((string)last.Tag); modified.Remove((string)last.Tag); list.Items.Remove(last);
                }
                item = new ListViewItem(new string[] { info.Name, info.LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss"), SizeLabel(info.Length) });
                item.Tag = path; item.Name = info.Name; item.ToolTipText = "文件名：" + info.Name;
                modified[path] = info.LastWriteTime;
                int position = 0;
                while (position < list.Items.Count && modified[(string)list.Items[position].Tag] >= info.LastWriteTime) position++;
                list.Items.Insert(position, item); rows[path] = item; RefreshOverview(); return true;
            } catch { return false; }
        }
        void Snapshot() {
            if (root == null || !SafePath(root)) return;
            // Only root files and today's known Codex subdirectory; never scan all history.
            var dirs = new List<string> { root };
            string today = Path.Combine(root, DateTime.Now.ToString("yyyy"), DateTime.Now.ToString("MM"), DateTime.Now.ToString("dd"));
            if (SafePath(today) && Directory.Exists(today)) dirs.Add(today);
            int examined = 0;
            foreach (string dir in dirs) {
                try { foreach (string p in Directory.EnumerateFiles(dir, "rollout-*.jsonl", SearchOption.TopDirectoryOnly)) {
                    if (++examined > 200) break; ShowMetadata(p);
                } } catch { }
                if (examined > 200) break;
            }
            status.Text = "已刷新当前目录与今日目录（最多检查200份文件，显示20份）。\n当前列表是文件快照；后续变化会在观察开启时更新。";
        }
        void StopWatch(string message) {
            FileSystemWatcher old;
            lock (gate) { old = watcher; watcher = null; generation++; pending.Clear(); posted = 0; }
            if (old != null) { old.EnableRaisingEvents = false; old.Dispose(); }
            status.Text = message;
        }
        void BindOwner(string id) {
            // Only the launching Hecate process. No access to any Codex process.
            int pid; if (!Int32.TryParse(id, out pid)) return;
            try {
                owner = System.Diagnostics.Process.GetProcessById(pid);
                owner.Exited += delegate {
                    try { BeginInvoke((MethodInvoker)delegate { Close(); }); }
                    catch (InvalidOperationException) { }
                };
                owner.EnableRaisingEvents = true;
                if (owner.HasExited) Close();
            } catch { Close(); }
        }
        protected override void OnFormClosing(FormClosingEventArgs e) {
            closing = true; StopWatch("已关闭。");
            if (owner != null) { owner.Dispose(); owner = null; }
            base.OnFormClosing(e);
        }
        [STAThread]
        static void Main(string[] args) {
            Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
            string path = args.Length > 0 ? args[0] : Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".codex", "sessions");
            var window = new ActivityWindow(path);
            if (args.Length > 1) window.Shown += delegate { window.BindOwner(args[1]); };
            Application.Run(window);
        }
    }
}
