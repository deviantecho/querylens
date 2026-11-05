'use strict';
const $ = (id) => document.getElementById(id);
const state = {token: null, plan: null, result: null, busy: false, publicDemo: false, currency: 'USD', dataset: null, trendData: null};
const money = (n) => n === null ? '—' : new Intl.NumberFormat('en-US', {style: 'currency', currency: state.currency, maximumFractionDigits: 0}).format(n);
const node = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };

async function api(path, body) {
  const response = await fetch(path, body ? {method: 'POST', headers: {'Content-Type': 'application/json', 'X-QueryLens-Token': state.token}, body: JSON.stringify(body)} : {});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'The request failed. Please try again.');
  return data;
}
function error(message) { $('query-error').hidden = !message; $('query-error').textContent = message || ''; }
function invalidate() {
  state.plan = null;
  $('run').disabled = true;
  $('review-state').textContent = 'Awaiting draft';
  $('review-state').className = 'tag neutral';
  $('review-empty').hidden = false;
  $('review-content').hidden = true;
  $('results').hidden = true;
  state.result = null;
}
function busy(value, message) {
  state.busy = value;
  ['question', 'sql-input', 'manual', 'examples', 'backend', 'retrieval'].forEach(id => { $(id).disabled = value; });
  $('draft').disabled = value || !state.token;
  $('draft').textContent = value ? message : 'Draft SQL ↗';
  $('run').disabled = value || !state.plan;
  $('open-import').disabled = value;
  document.querySelector('[data-view="import-view"]').disabled = value;
  $('query-status').textContent = value ? message : 'Ready';
}
function table(target, columns, rows) {
  target.replaceChildren();
  if (!rows.length) { target.append(node('p', 'No rows to show.', 'muted')); return; }
  const t = node('table'), head = node('thead'), tr = node('tr'), body = node('tbody');
  columns.forEach((c) => { const th = node('th', c.replaceAll('_', ' ')); th.scope = 'col'; tr.append(th); });
  head.append(tr);
  rows.forEach((r) => { const line = node('tr'); r.forEach((v) => line.append(node('td', v === null ? 'NULL' : typeof v === 'number' ? new Intl.NumberFormat('en-US', {maximumFractionDigits: 2}).format(v) : String(v)))); body.append(line); });
  t.append(head, body); target.append(t);
}
function trend(data) {
  const svgNS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(svgNS, 'svg');
  const width = Math.max(280, $('trend-chart').clientWidth);
  svg.setAttribute('viewBox', `0 0 ${width} 190`); svg.setAttribute('role', 'img'); svg.setAttribute('aria-label', `Monthly net revenue in ${state.currency} for ${state.dataset?.shop_name || 'the shop'}`);
  const add = (tag, attrs, text) => {const n = document.createElementNS(svgNS, tag); Object.entries(attrs).forEach(([k,v]) => n.setAttribute(k, v)); if (text !== undefined) n.textContent = text; svg.append(n); return n;};
  const values = data.rows.map((r) => Number(r[1]) || 0), max = Math.max(1, ...values);
  const x = (i) => values.length === 1 ? width / 2 : 46 + i * (width - 64) / Math.max(1, values.length - 1), y = (v) => 150 - v / max * 125;
  const compact = new Intl.NumberFormat('en-US', {notation:'compact', maximumFractionDigits:1});
  for(let i=0;i<=3;i++){const v = max * i / 3; add('line', {x1:44,y1:y(v),x2:width-8,y2:y(v),class:'gridline'}); add('text',{x:2,y:y(v)+4}, compact.format(v));}
  const points = values.map((v,i) => `${x(i)},${y(v)}`).join(' ');
  add('polygon', {points:`${x(0)},150 ${points} ${x(values.length-1)},150`,class:'area'});
  add('polyline', {points,class:'line'});
  values.forEach((v,i) => {const dot = add('circle',{cx:x(i),cy:y(v),r:3,class:'point'}); const title=document.createElementNS(svgNS,'title'); title.textContent=`${data.rows[i][0].slice(0,7)}: ${money(v)}`;dot.append(title);if(i%Math.max(1,Math.ceil(values.length/6))===0||i===values.length-1)add('text',{x:x(i),y:179,'text-anchor':'middle'},new Date(`${data.rows[i][0].slice(0,10)}T12:00:00Z`).toLocaleDateString('en-US',{month:'short',year:'2-digit',timeZone:'UTC'}));});
  $('trend-chart').replaceChildren(svg); $('trend-chart').setAttribute('aria-busy','false');
}
function channels(data) {
  $('channel-chart').replaceChildren();
  const max = Math.max(1,...data.rows.map(r=>r[1]));
  data.rows.forEach(([label,value])=>{const row=node('div',undefined,'channel-row'), text=node('div');text.append(node('span',label),node('strong',money(value))); const track=node('div',undefined,'bar-track'),bar=node('div',undefined,'bar');bar.style.width=`${value/max*100}%`;track.append(bar);row.append(text,track);$('channel-chart').append(row);});
}
function context(data) {
  $('schema-list').replaceChildren(); $('rules-list').replaceChildren();
  Object.entries(data.schema).forEach(([name,schema])=>{const s=node('section');s.append(node('h2',name),node('p',schema.description));Object.entries(schema.columns).forEach(([column,type])=>{const r=node('div',undefined,'column');r.append(node('span',column),node('span',type));s.append(r);});$('schema-list').append(s);});
  data.rules.forEach(r=>{const section=node('section',undefined,'rule');section.append(node('h3',r.title),node('p',r.text));$('rules-list').append(section);});
}
async function history() {
  $('history-status').textContent='Loading query history...';
  try {const entries=await api('/api/history');table($('history-table'),['time','question','source','status','rows','duration (ms)','detail'],entries.map(r=>[new Date(r.created).toLocaleString(),r.question,r.source,r.status,r.row_count,r.duration_ms,r.detail]));$('history-status').textContent=entries.length?`${entries.length} recent records`:'Run a reviewed query to start your history.';}
  catch(e){$('history-status').textContent=e.message;}
}
function showView(id) {
  const button=document.querySelector(`[data-view="${id}"]`);
  document.querySelectorAll('.view').forEach(v=>v.hidden=v.id!==id);
  document.querySelectorAll('[data-view]').forEach(b=>{b.classList.toggle('active',b===button);if(b===button)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});
  $('breadcrumb').textContent=button.textContent.replace(/\d/g,'').trim();
  if(id==='history')history();
  if(id==='ai-lab')aiStatus();
  $('main').focus();
  window.scrollTo({top:0,behavior:'instant'});
}
document.querySelectorAll('[data-view]').forEach(button=>button.addEventListener('click',()=>showView(button.dataset.view)));
$('refresh-history').addEventListener('click',history);
['question','sql-input','manual','retrieval'].forEach(id=>$(id).addEventListener('input',()=>{invalidate();error(null);}));
$('backend').addEventListener('change',()=>{invalidate();error(null);updateMode();});
$('examples').addEventListener('change',()=>{if(!$('examples').value)return;$('question').value=$('examples').value;$('manual').checked=false;invalidate();error(null);});
$('query-form').addEventListener('submit',async event=>{
  event.preventDefault();if(state.busy)return;invalidate();error(null);busy(true,'Planning query...');
  try {
    const body={question:$('question').value,backend:$('backend').value,retrieval:$('retrieval').checked};if($('manual').checked)body.sql=$('sql-input').value;
    const plan=await api('/api/plan',body);state.plan=plan;
    $('review-empty').hidden=true;$('review-content').hidden=false;$('review-state').textContent='Ready for review';$('review-state').className='tag';
    $('sql-preview').textContent=plan.sql;$('planned-preview').textContent=plan.planned_sql;$('explanation').textContent=plan.explanation;$('source').textContent=`${plan.source} · Models: ${plan.tables.join(', ')}`;$('model-version').textContent=`Model version: ${plan.model_version} · Calculated fields: ${plan.calculated_fields.join(', ') || 'none'}`;
    $('inference-trace').textContent=JSON.stringify(plan.ai_trace,null,2);
    $('context-list').replaceChildren(...plan.context.map(r=>{const li=node('li',r.title);li.title=r.text;return li;}));
  } catch(e){error(e.message);} finally{busy(false);}
});
$('run').addEventListener('click',async()=>{
  if(!state.plan||state.busy)return;error(null);busy(true,'Running query...');
  try{const result=await api('/api/execute',{plan_id:state.plan.id});state.result=result;table($('result-table'),result.columns,result.rows);$('result-meta').textContent=`${result.row_count} rows · ${result.duration_ms} ms · ${result.source}${result.truncated?' · Limited to 200 rows':''}`;$('results').hidden=false;$('review-state').textContent='Executed';$('query-status').textContent=`Query complete. ${result.row_count} rows returned.`;}
  catch(e){error(e.message);}finally{busy(false);}
});
$('export').addEventListener('click',()=>{
  if(!state.result)return;
  const cell=value=>{let text=value===null?'':String(value);if(typeof value==='string'&&/^[=+\-@\t\r]/.test(text))text="'"+text;return '"'+text.replaceAll('"','""')+'"';};
  const csv=[state.result.columns,...state.result.rows].map(row=>row.map(cell).join(',')).join('\r\n');
  const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8;'}));const a=node('a');a.href=url;a.download='querylens-results.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
});
function updateMode(){
  const labels={local:'Local language model',intent:'Trained ML model',examples:'Example mode',ollama:'Local Ollama model'};
  const notes={local:'Qwen runs on this computer and generates new SQL using your schema. Drafts can take 10–30 seconds on CPU. Inspect every draft before running it.',intent:'A calibrated classifier recognizes nine unfiltered report types and selects approved SQL templates. It abstains on uncertain questions; use the language model for filters.',examples:'A fixed library of nine example questions. No model inference in this mode.',ollama:'A separately installed Ollama model generates SQL locally.'};
  if(state.publicDemo)notes.intent='The live trained classifier recognizes nine unfiltered report types and selects approved SQL. Try rephrasing the examples. For filters, use the SQL editor or run Qwen in the local version.';
  $('mode').textContent=labels[$('backend').value];$('mode-note').textContent=notes[$('backend').value];
}
async function aiStatus(){
  $('ai-status').textContent='Loading local AI results...';
  try{
    const data=await api('/api/ai/status'),ml=data.intent_model,e=ml.evaluation,pct=n=>`${(n*100).toFixed(1)}%`;
    $('ai-status').textContent=data.public_demo?'Live inference: trained intent classifier. Generation scores below are saved CPU-local Qwen experiments; Qwen does not run on this free web instance.':`Default inference: ${data.default_backend}. ${data.local_model_ready?'Local model weights and runtime available.':'Local model not ready; the trained classifier is available.'}`;
    $('ml-accuracy').textContent=pct(e.accuracy);$('ml-f1').textContent=e.macro_f1.toFixed(3);$('ml-coverage').textContent=pct(e.coverage);$('ml-ood').textContent=pct(e.ood_rejection_rate);
    $('ml-split').textContent=`${ml.training_count} train / ${ml.dev_count} dev / ${ml.test_count} test questions`;
    $('ml-selective').textContent=`Accepted accuracy: ${e.selective_accuracy===null?'N/A':pct(e.selective_accuracy)}`;
    $('ml-ood-count').textContent=`${e.ood_count} held-out unsupported questions`;
    table($('confusion-table'),['true / predicted',...e.labels],e.confusion_matrix.map((r,i)=>[e.labels[i],...r]));
    if(data.generation_evaluation){
      const report=data.generation_evaluation;
      table($('generation-table'),['variant','correct / total','execution accuracy','95% interval','valid SQL','mean latency'],report.variants.map(v=>[v.name,`${v.correct} / ${v.count}`,pct(v.execution_accuracy),v.accuracy_95pct_wilson.map(pct).join(' to '),pct(v.sql_validity_rate),`${(v.mean_latency_ms/1000).toFixed(2)} s`]));
      $('generation-note').textContent=`Saved run: ${new Date(report.created).toLocaleString()}. ${report.provenance}`;
    }else{$('generation-table').replaceChildren(node('p','No saved generation experiment yet. Run python -m querylens --ai-eval locally.','muted'));}
    $('ai-provenance').replaceChildren();
    [['Trained NLP model','Word and character TF-IDF features with logistic regression, calibrated using three-fold cross-validation on training data. Thresholds use only the dev split.'],['Local language model',`${data.local_model}. Pretrained open weights; this project performs local inference, not language-model pretraining or fine-tuning.`],['Context retrieval',`${data.retrieval.method}. ${data.retrieval.documents} documents from schema, business rules, and training examples. Test questions are not indexed.`],['Question data',data.data_provenance]].forEach(([title,text])=>{const r=node('div',undefined,'rule');r.append(node('h3',title),node('p',text));$('ai-provenance').append(r);});
  }catch(e){$('ai-status').textContent=e.message;}
}
$('refresh-ai').addEventListener('click',aiStatus);
function applyWorkspace(data) {
    state.token=data.token;state.dataset=data.dataset;state.currency=data.dataset.currency;state.trendData=data.trend;invalidate();error(null);
    $('metric-revenue').textContent=money(data.metrics.net_revenue);$('metric-orders').textContent=data.metrics.completed_orders.toLocaleString('en-US');$('metric-aov').textContent=money(data.metrics.average_order_value);$('metric-refunds').textContent=data.metrics.refund_rate_pct===null?'—':`${data.metrics.refund_rate_pct}%`;
    state.publicDemo=Boolean(data.deployment?.public_demo);
    const localOption=$('backend').querySelector('[value="local"]');localOption.disabled=!data.ai.local_model_ready;
    if(state.publicDemo){localOption.disabled=true;localOption.textContent='Qwen — available in local version';$('demo-note').hidden=false;$('history-scope').textContent='Execution results and rejected drafts from your current browser workspace. Temporary and separate from other visitors.';}
    const uploaded=data.dataset.kind==='upload';
    $('workspace-kind').textContent=uploaded?'Your shop · temporary':state.publicDemo?'Public demo':'Local workspace';
    $('dataset-title').textContent=data.dataset.shop_name;
    $('dataset-detail').textContent=uploaded?`${data.dataset.filename} · ${data.dataset.order_count.toLocaleString()} orders · ${state.currency} · Temporary upload`:'Synthetic commerce data · USD · Sample shop';
    $('dataset-footer').textContent=uploaded?`${data.dataset.shop_name} · Uploaded orders · ${state.currency}`:'Reproducible demo · Synthetic commerce data · USD';
    $('reporting-period').textContent=data.period;$('trend-unit').textContent=`Monthly net revenue · ${state.currency}`;$('trend-count').textContent=`${data.trend.rows.length} ${data.trend.rows.length===1?'month':'months'} with orders`;
    $('dataset-warnings').hidden=!data.dataset.warnings.length;$('dataset-warnings').textContent=data.dataset.warnings.join(' ');
    $('upload-active').hidden=!uploaded;$('upload-active-description').textContent=uploaded?`${data.dataset.shop_name}: ${data.dataset.order_count.toLocaleString()} orders, ${data.period}, ${state.currency}. Your upload is temporary; keep the original file.`:'';
    $('open-import').textContent=uploaded?'Manage shop data →':'Use your shop data →';
    $('history-table').replaceChildren();$('history-status').textContent='';
    if(data.mode==='ollama'&&!$('backend').querySelector('[value="ollama"]')){$('backend').append(node('option','Local Ollama model'));$('backend').lastChild.value='ollama';}
    $('backend').value=data.mode;updateMode();
    $('examples').replaceChildren(node('option','Try an example question'));$('examples').firstChild.value='';
    data.examples.forEach(e=>{const option=node('option',e.question);option.value=e.question;$('examples').append(option);});trend(data.trend);channels(data.channels);context(data);$('draft').disabled=false;
    $('boot-error').hidden=true;
}
new ResizeObserver(()=>{if(state.trendData)trend(state.trendData);}).observe($('trend-chart'));
(async()=>{
  try{applyWorkspace(await api('/api/bootstrap'));
  }catch(e){$('boot-error').textContent=`Could not load the workspace: ${e.message}. Refresh after checking the local server.`;$('boot-error').hidden=false;$('mode').textContent='Connection unavailable';}
})();
