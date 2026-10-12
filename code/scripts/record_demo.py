"""Drive the real CrashLens web UI with Playwright (installed Edge) and record a demo video.

Requires: pip install playwright && python -m playwright install ffmpeg
Output: video/raw/video-out/*.webm (convert with ffmpeg to video/demo.mp4).
"""
import os, shutil, subprocess, sys, time, urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
PY = Path(sys.executable)
SP = ROOT / "video" / "raw"
DATA = SP / "demo-data"
VID = SP / "video-out"
PORT = 8791
URL = f"http://127.0.0.1:{PORT}"
FIXED = str(ROOT / "code" / "examples" / "datacraft-fixed")

CAPTION_JS = """(text) => {
  let el = document.getElementById('__cap');
  if (!el) { el = document.createElement('div'); el.id='__cap';
    el.style.cssText='position:fixed;left:50%;bottom:28px;transform:translateX(-50%);z-index:2147483647;'+
      'max-width:80%;padding:12px 22px;border-radius:10px;background:rgba(15,23,42,.88);color:#fff;'+
      'font:600 20px/1.5 "Microsoft YaHei",sans-serif;text-align:center;box-shadow:0 6px 24px rgba(0,0,0,.35);pointer-events:none';
  }
  const host = document.querySelector('dialog[open]') || document.documentElement;
  if (el.parentNode !== host) host.appendChild(el);
  el.textContent = text; el.style.display = text ? 'block' : 'none';
}"""


def main():
    shutil.rmtree(DATA, ignore_errors=True); shutil.rmtree(VID, ignore_errors=True)
    env = dict(os.environ, PYTHONUTF8="1")
    server = subprocess.Popen([str(PY), "-m", "crashlens", "serve", "--port", str(PORT), "--data-dir", str(DATA)],
                              cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try: urllib.request.urlopen(URL, timeout=1); break
            except Exception: time.sleep(0.5)
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True)
            ctx = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme="light", bypass_csp=True,
                                      record_video_dir=str(VID), record_video_size={"width": 1440, "height": 900})
            page = ctx.new_page()
            cap = lambda t, wait=0: (page.evaluate(CAPTION_JS, t), page.wait_for_timeout(wait))
            page.goto(URL); page.wait_for_timeout(800)
            cap("CrashLens 软件测试平台：输入待测软件目录 → 动态执行 → 捕获崩溃/异常 → 输出 Bug 报告", 4500)
            cap("待测软件：DataCraft（命令行 JSON 处理程序），含教学用预设缺陷", 3000)

            # 1. 输入：待测软件目录
            page.click("#use-buggy"); page.wait_for_timeout(1200)
            cap("① 输入待测软件所在目录，平台自动读取 crashlens.toml（启动命令、输入方式、种子）", 4500)
            page.hover("#command"); cap("启动命令 [\"{python}\", \"datacraft.py\"]，通过标准输入传入测试数据", 3500)
            page.hover("#max-cases"); cap("生成 80 个测试用例，单次超时 1 秒，随机种子 42（结果可复现）", 3500)

            # 2. 动态执行
            cap("② 开始动态测试：真实启动目标进程，执行变异生成的输入", 2000)
            page.click("#start")
            page.wait_for_selector("#job-view:not([hidden])")
            cap("正在执行：正常种子预检 → 边界值 / JSON 结构变异 / 字节变异", 0)
            page.wait_for_function("document.getElementById('state-badge').textContent==='已完成'", timeout=240000)
            page.wait_for_timeout(1500)
            job_url = page.url
            cap("③ 测试完成：未捕获异常、超时等失败被自动捕获并按类型与位置归组", 4500)
            page.hover("#spectrum"); cap("结果谱带：通过 / 正常拒绝 / 异常 / 超时 的分布", 3000)
            page.locator("#findings").scroll_into_view_if_needed(); page.mouse.wheel(0, 350)
            cap("发现列表：每个分组都有出现次数、首次用例号、重放一致性和输入缩减结果", 5000)

            # 3. 查看证据（优先 ZeroDivisionError）
            cards = page.locator("#findings article")
            target = cards.filter(has_text="ZeroDivisionError")
            target = target.first if target.count() else cards.first
            target.scroll_into_view_if_needed(); target.locator("button").click()
            page.wait_for_selector("#evidence-dialog[open]"); page.wait_for_timeout(800)
            cap("④ 查看 Bug 证据：触发输入、退出状态、两次重放均复现", 4500)
            dlg = page.locator("#evidence-dialog")
            for msg in ("错误堆栈：定位到 datacraft.py 中出错的代码行", "自动缩减后的最小触发输入（已重放验证）"):
                dlg.hover(); page.mouse.wheel(0, 420); cap(msg, 3500)
            dlg.hover(); page.mouse.wheel(0, 600); page.wait_for_timeout(500)

            # 4. 重放
            cap("⑤ 一键重放失败用例，确认 Bug 稳定可复现", 2500)
            page.click("#replay-evidence")
            page.wait_for_function("document.getElementById('job-title').textContent==='失败用例重放' && document.getElementById('state-badge').textContent==='已完成'", timeout=120000)
            page.wait_for_timeout(800)
            cap("重放结果：再次观察到相同失败签名 —— Bug 可复现", 4500)

            # 5. 修复版本回归
            page.goto('about:blank'); page.goto(job_url); page.wait_for_function("document.getElementById('state-badge').textContent==='已完成'")
            page.wait_for_timeout(800)
            cards = page.locator("#findings article")
            target = cards.filter(has_text="ZeroDivisionError")
            target = target.first if target.count() else cards.first
            target.locator("button").click(); page.wait_for_selector("#evidence-dialog[open]")
            page.locator("#regression-directory").scroll_into_view_if_needed()
            page.fill("#regression-directory", FIXED)
            cap("⑥ 修复版本回归：用修复后的 datacraft-fixed 运行同一触发输入", 3500)
            page.click("#regression-evidence")
            page.wait_for_function("document.getElementById('job-title').textContent==='修复版本回归' && document.getElementById('state-badge').textContent==='已完成'", timeout=120000)
            page.wait_for_timeout(800)
            cap("回归结果：此输入已被正常处理或拒绝，原异常不再出现", 4500)

            # 6. 输出：报告
            page.goto('about:blank'); page.goto(job_url); page.wait_for_function("document.getElementById('state-badge').textContent==='已完成'")
            href = page.get_attribute("#html-report", "href")
            page.locator("#html-report").scroll_into_view_if_needed(); page.hover("#html-report")
            cap("⑦ 输出：导出 HTML / JSON 报告，或下载完整证据 ZIP", 3500)
            page.set_content(page.request.get(URL + href).text()); page.wait_for_timeout(1000)
            cap("离线 HTML 报告：列出在待测软件中找到的全部 Bug 及证据", 4000)
            page.mouse.wheel(0, 500); page.wait_for_timeout(1500)
            page.get_by_text("发现与证据").first.evaluate("e => e.scrollIntoView({behavior:'smooth'})")
            page.wait_for_timeout(1200)
            cap("报告中的每个 Bug：失败分类、触发输入、错误堆栈、重放与缩减记录", 3000)
            for _ in range(6):
                page.mouse.wheel(0, 450); page.wait_for_timeout(1400)
            page.evaluate("window.scrollTo(0,0)"); page.wait_for_timeout(500)
            cap("演示完成：目录输入 → 动态执行 → 捕获崩溃 → 复现 / 回归 → Bug 报告", 4500)
            video = page.video
            ctx.close(); browser.close()
            print("VIDEO", video.path())
    finally:
        server.terminate()
        try: server.wait(10)
        except Exception: server.kill()


if __name__ == "__main__":
    main()
