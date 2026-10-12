"use strict";
const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="crashlens-token"]').content;
const states = {queued:"排队中",running:"运行中",completed:"已完成",cancelled:"已停止",failed:"执行失败",interrupted:"运行中断"};
const categories = {exception:"未捕获异常",crash:"进程崩溃",timeout:"超时",abnormal_exit:"异常退出",output_limit:"输出超限",passed:"通过",rejected:"正常拒绝",cancelled:"已停止"};
const spectrumOrder = ["passed","rejected","exception","crash","abnormal_exit","output_limit","timeout","cancelled"];
let selected = null, lastJob = null, loadedConfig = null, loading = false;
const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
function notice(message) { $("notice").textContent = message; $("notice").hidden = !message; }
const prefersDark = () => matchMedia("(prefers-color-scheme: dark)").matches;
function applyTheme(mode) {
  if (mode) document.documentElement.dataset.theme = mode; else delete document.documentElement.dataset.theme;
  $("theme-toggle").textContent = (mode ? mode === "dark" : prefersDark()) ? "切换浅色界面" : "切换深色界面";
}
try { applyTheme(localStorage.getItem("crashlens-theme")); } catch { applyTheme(null); }
$("theme-toggle").onclick = () => {
  const mode = document.documentElement.dataset.theme;
  const next = (mode ? mode === "dark" : prefersDark()) ? "light" : "dark";
  try { localStorage.setItem("crashlens-theme", next); } catch {}
  applyTheme(next);
};
// 证据谱带：按分类切分本次运行的全部结果，未执行的预算留作条纹留白。
function spectrum(job) {
  const strip = $("spectrum"), counts = job.counts;
  const parts = spectrumOrder.filter(key => counts[key] > 0).map(key => [key, counts[key]]);
  const done = parts.reduce((sum, [, n]) => sum + n, 0);
  const total = Math.max(job.source ? 1 : job.config.fuzz.max_cases, done, 1);
  const remaining = Math.max(total - done, 0);
  const segment = (className, grow, title) => {
    const node = document.createElement("i");
    node.className = className; node.title = title; node.style.flexGrow = grow;
    return node;
  };
  strip.replaceChildren(
    ...parts.map(([key, n]) => segment(key, n, `${categories[key] || key} · ${n}`)),
    ...(remaining ? [segment("remaining", remaining, `未执行预算 · ${remaining}`)] : []));
  strip.setAttribute("aria-valuemin", "0"); strip.setAttribute("aria-valuemax", total);
  strip.setAttribute("aria-valuenow", done);
  strip.setAttribute("aria-valuetext", `已执行 ${done} / ${total} 个用例`);
  $("spectrum-legend").innerHTML = parts.map(([key, n]) =>
    `<b class="${esc(key)}">${esc(categories[key] || key)} <span>${n}</span></b>`).join("")
    + (remaining ? `<b>未执行预算 <span>${remaining}</span></b>` : "");
}
async function api(path, method="GET", body) {
  const response = await fetch(path,{method,headers:{"Content-Type":"application/json","X-CrashLens-Token":token},body:body === undefined ? undefined : JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail));
  return data;
}
function fill(config) {
  loadedConfig = config;
  const t=config.target,f=config.fuzz;
  $("command").value=JSON.stringify(t.command);$("input-mode").value=t.input_mode;$("timeout").value=t.timeout_seconds;
  $("seed-dir").value=f.seed_directory;$("max-cases").value=f.max_cases;$("random-seed").value=f.random_seed;
  $("max-seconds").value=f.max_seconds;$("minimize").checked=f.minimize;$("reject-codes").value=t.reject_codes.join(",");
}
async function inspect() {
  notice("");
  try {const data=await api("/api/inspect","POST",{directory:$("directory").value});
    if(data.config) {fill(data.config);notice("已读取 crashlens.toml，请确认启动方式与测试预算。");}
    else {loadedConfig=null;notice(`没有配置文件。候选入口：${data.candidates.join("、") || "未识别"}。请填写命令并准备正常种子。`);}
  }catch(error){notice(error.message);}
}
$("inspect").onclick=inspect;
$("use-buggy").onclick=()=>{$("directory").value=document.body.dataset.buggy;inspect();};
$("use-fixed").onclick=()=>{$("directory").value=document.body.dataset.fixed;inspect();};
$("directory").oninput=()=>{loadedConfig=null;};
function newView(){selected=null;lastJob=null;$("create-view").hidden=false;$("job-view").hidden=true;$("page-label").textContent="创建测试";notice("");history.replaceState(null,"",location.pathname);refreshHistory();}
$("nav-new").onclick=newView;$("back").onclick=newView;
$("create-form").onsubmit=async event=>{
  event.preventDefault();$("start").disabled=true;notice("");
  try{
    const config=loadedConfig ? structuredClone(loadedConfig) : {target:{},fuzz:{}};
    Object.assign(config.target,{command:JSON.parse($("command").value),input_mode:$("input-mode").value,timeout_seconds:Number($("timeout").value),reject_codes:$("reject-codes").value.split(",").filter(x=>x.trim()!=="").map(Number)});
    Object.assign(config.fuzz,{seed_directory:$("seed-dir").value,max_cases:Number($("max-cases").value),random_seed:Number($("random-seed").value),max_seconds:Number($("max-seconds").value),minimize:$("minimize").checked});
    const job=await api("/api/jobs","POST",{directory:$("directory").value,config});await selectJob(job.id);
  }catch(error){notice(error.message);}finally{$("start").disabled=false;}
};
async function refreshHistory(){
  const jobs=await api("/api/jobs");$("history-count").textContent=jobs.length;
  const html=jobs.map(j=>`<button data-job="${esc(j.id)}" class="${esc(j.state)}${j.id===selected?" selected":""}">${esc(j.directory.split(/[\\/]/).pop())}<small>${esc(states[j.state] || j.state)} · ${j.finding_count} 个分组 · ${esc(j.created_at.slice(11,19))} UTC</small></button>`).join("") || '<p class="hint">完成第一项测试后，记录会显示在这里。</p>';
  if($("history").innerHTML!==html){$("history").innerHTML=html;$("history").querySelectorAll("button").forEach(button=>button.onclick=()=>selectJob(button.dataset.job).catch(e=>notice(e.message)));}
}
async function selectJob(id){selected=id;$("create-view").hidden=true;$("job-view").hidden=false;$("page-label").textContent="测试详情";notice("");history.replaceState(null,"",`#${id}`);await refreshJob();await refreshHistory();}
function render(job){
  if(lastJob && JSON.stringify(lastJob)===JSON.stringify(job))return;
  lastJob=job;const counts=job.counts,active=["running","queued"].includes(job.state);
  $("job-id").textContent=`TEST RUN / ${job.id}`;$("job-title").textContent=job.source ? (job.source.kind==="regression" ? "修复版本回归" : "失败用例重放") : "动态测试结果";
  $("job-directory").textContent=job.directory;$("state-badge").textContent=states[job.state]||job.state;$("state-badge").className=`badge ${job.state}`;
  $("current").textContent=job.current;$("elapsed").textContent=`${(job.elapsed_seconds||0).toFixed(1)} s`;
  $("stop").hidden=!active;spectrum(job);
  $("metric-cases").textContent=job.executed;$("aux-count").textContent=`另有 ${job.auxiliary_executions} 次重放 / 缩减执行`;
  $("metric-findings").textContent=job.finding_count;$("metric-normal").textContent=`${counts.passed||0} / ${counts.rejected||0}`;
  $("metric-errors").textContent=`${(counts.exception||0)+(counts.crash||0)} / ${counts.timeout||0}`;$("finding-total").textContent=job.findings.length;
  $("json-report").href=`/api/jobs/${job.id}/report.json`;$("html-report").href=`/api/jobs/${job.id}/report.html`;
  $("zip-report").href=`/api/jobs/${job.id}/evidence.zip`;$("zip-report").hidden=active;
  $("comparison").hidden=!job.comparison;
  if(job.comparison){
    const c=job.comparison,v=c.verdict||(c.same_failure ? "reproduced" : "inconclusive");
    const titles={reproduced:"再次观察到相同失败签名",handled:"此输入已正常处理或拒绝",different_failure:"出现了不同的失败",inconclusive:"无法得出回归结论"};
    const explanations={reproduced:"同一输入再次触发了原来的失败。",handled:"该输入已通过测试或被程序正常拒绝。可以继续测试其他输入。",different_failure:"查看本次错误日志，排查新出现的问题。",inconclusive:"请检查任务错误和正常样例的运行结果，再重新执行。"};
    $("comparison").innerHTML=`<strong>${titles[v]||titles.inconclusive}</strong><p>${c.category ? `当前分类：${esc(categories[c.category]||c.category)}。` : ""}${explanations[v]||explanations.inconclusive}</p>`;
  }
  if(job.error)notice(job.error);
  $("findings").innerHTML=job.findings.map(f=>`<article class="card finding ${esc(f.category)}"><div><div class="finding-title"><span class="badge ${esc(f.category)}">${esc(categories[f.category])}</span><strong>${esc(f.identity.split(":")[0])}</strong></div><p>出现 <span class="mono">${f.occurrences}</span> 次 · 首次用例 <span class="mono">#${f.first_case}</span> · <span class="mono">${esc(f.strategy)}</span> · ${f.stable ? "2/2 重放一致" : "重放待完成或不稳定"}${f.minimization?.verified ? ` · 输入 <span class="mono">${f.minimization.original_bytes} → ${f.minimization.reduced_bytes} B</span>` : ""}</p></div><button class="secondary" data-finding="${f.id}">查看证据 ↗</button></article>`).join("") || `<div class="empty"><b>${active ? "正在执行并收集证据" : "本次没有观察到目标失败"}</b>${active ? "发现的异常会在这里实时显示。" : "可查看分类计数，或调整种子与测试预算继续探索。"}</div>`;
  $("findings").querySelectorAll("button").forEach(button=>button.onclick=()=>showEvidence(job.id,button.dataset.finding).catch(e=>notice(e.message)));
}
async function refreshJob(){if(!selected)return;const id=selected;const job=await api(`/api/jobs/${id}`);if(id===selected)render(job);}
$("stop").onclick=async()=>{try{await api(`/api/jobs/${selected}/stop`,"POST",{});notice("已请求停止，正在清理当前测试进程。");}catch(e){notice(e.message);}};
$("close-evidence").onclick=()=>$("evidence-dialog").close();
async function showEvidence(jobId,findingId){
  const data=await api(`/api/jobs/${jobId}/findings/${findingId}/preview`),f=data.finding;
  $("evidence-title").textContent=`${categories[f.category]} · ${f.identity.split(":")[0]}`;
  const reductionMethod=f.minimization?.method==="json-structure" ? "JSON 结构化缩减" : "字节片段删除";
  $("evidence-content").innerHTML=`<p>签名 ${esc(f.id)} · 退出状态 ${esc(f.result.returncode)} · ${f.result.duration_seconds} s · ${f.stable ? "两次验证均复现" : "尚未确认稳定性"}</p><h3>触发输入 ${f.result.input_bytes} B ${data.truncated ? "（仅预览前 16 KiB）" : ""}</h3><pre>${esc(data.input) || "（空输入）"}</pre><p>SHA-256：${esc(f.result.input_sha256)}</p><details><summary>前 128 字节十六进制</summary><pre>${esc(data.hex)}</pre></details><h3>标准错误 / 堆栈</h3><pre>${esc(f.result.stderr) || "（无标准错误输出）"}</pre><h3>标准输出</h3><pre>${esc(f.result.stdout) || "（无标准输出）"}</pre>${f.result.output_truncated ? '<p>输出超过上限，此处显示截取内容。</p>' : ""}${data.minimized!==null ? `<h3>已验证的缩减输入 ${f.minimization.reduced_bytes} B</h3><pre>${esc(data.minimized)||"（空输入）"}</pre><p>${reductionMethod} · 尝试 ${f.minimization.attempts} 次，缩减后已重放验证。</p>` : ""}<div class="evidence-actions"><a class="secondary link-button" href="/api/jobs/${jobId}/findings/${findingId}/input">下载原始输入</a>${data.minimized!==null ? `<a class="secondary link-button" href="/api/jobs/${jobId}/findings/${findingId}/input?minimized=true">下载缩减输入</a>` : ""}<button class="primary" id="replay-evidence">重放失败用例</button></div><h3>修复版本回归</h3><p>填写修复版本目录，使用该目录的 crashlens.toml 运行同一输入。</p><div class="regression-row"><input id="regression-directory" placeholder="修复版本所在目录" value="${esc(document.body.dataset.fixed)}"><button class="secondary" id="regression-evidence">运行回归验证</button></div><h3>独立复现</h3><pre>crashlens replay ${esc(JSON.stringify(lastJob.directory))} "下载的 input.bin 路径"</pre>`;
  const replay=async(directory)=>{try{const job=await api(`/api/jobs/${jobId}/findings/${findingId}/replay`,"POST",{directory:directory||null,minimized:true});$("evidence-dialog").close();await selectJob(job.id);}catch(e){$("evidence-dialog").close();notice(e.message);}};
  $("replay-evidence").onclick=()=>replay(null);$("regression-evidence").onclick=()=>{const value=$("regression-directory").value.trim();if(!value){$("regression-directory").focus();return;}replay(value);};
  $("evidence-dialog").showModal();
}
async function poll(){if(loading)return;loading=true;try{await refreshHistory();await refreshJob();}catch(e){notice(e.message);}finally{loading=false;}}
if(location.hash.match(/^#[a-f0-9]{16}$/))selectJob(location.hash.slice(1)).catch(e=>notice(e.message));else refreshHistory().catch(e=>notice(e.message));
setInterval(poll,1200);
