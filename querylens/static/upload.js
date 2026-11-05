'use strict';
const uploadState = {file: null, content: null, inspected: null, preview: null, busy: false, statusVersion: 0};
const uploadAssumptions = {
  order_id: 'No order ID: internal IDs will be generated. Duplicate orders cannot be detected without your order IDs.',
  refund_amount: 'No refund amount: every refund is assumed to be zero.',
  status: 'No order status: every order is assumed to be completed.',
  customer_id: 'No customer ID: customer rankings and repeat-customer analysis are unavailable.',
  channel: 'No sales channel: the channel report is unavailable.',
  region: 'No customer region: the regional report is unavailable.'
};
function uploadError(message) { $('upload-error').hidden=!message; $('upload-error').textContent=message||'';if(message)$('upload-error').scrollIntoView({block:'center'}); }
function uploadStep(step) {
  $('upload-choose').hidden=step!==1; $('upload-matching').hidden=step!==2; $('upload-review').hidden=step!==3;
  $('upload-active').hidden=step!==1||state.dataset?.kind!=='upload';
  for(let i=1;i<=3;i++) {const item=$(`upload-step-${i}`);item.classList.toggle('active',i===step);if(i===step)item.setAttribute('aria-current','step');else item.removeAttribute('aria-current');}
  const panel=$(step===1?'upload-choose':step===2?'upload-matching':'upload-review');if(!$('import-view').hidden)panel.scrollIntoView({block:'start'});
}
function uploadBusy(value,message='') {
  uploadState.busy=value;busy(value,'Updating workspace...');
  document.querySelectorAll('#import-view input,#import-view select,#import-view button,[data-view]').forEach(e=>{e.disabled=value;});
  $('upload-message').textContent=message;
  if(!value){$('inspect-upload').disabled=!uploadState.file;$('commit-upload').disabled=!uploadState.preview;updateAssumptions();}
}
function mappingValues() {
  return Object.fromEntries((uploadState.inspected?.fields||[]).map(f=>[f.key,$(`map-${f.key}`).value]));
}
function updateAssumptions() {
  if(!uploadState.inspected||!$('map-customer_id'))return;
  const mapping=mappingValues(), name=$('map-customer_name');
  name.disabled=uploadState.busy||!mapping.customer_id;
  if(!mapping.customer_id)name.value='';
  $('upload-assumptions').replaceChildren(...Object.entries(uploadAssumptions).filter(([key])=>!mapping[key]).map(([,text])=>node('li',text)));
  if(!$('upload-assumptions').childNodes.length)$('upload-assumptions').append(node('li','Every main field is matched. Only the selected worksheet and currency will be imported.'));
}
function invalidateUpload() {
  uploadState.preview=null;$('commit-upload').disabled=true;$('upload-defaults-confirm').checked=false;uploadError(null);updateAssumptions();
}
async function statusMatches() {
  const version=++uploadState.statusVersion,column=$('map-status').value;
  $('upload-status-matches').replaceChildren();$('upload-status-section').hidden=!column;
  if(!column)return;
  $('validate-upload').disabled=true;
  try {
    const result=await api('/api/import/statuses',{upload_id:uploadState.inspected.upload_id,column});
    if(version!==uploadState.statusVersion)return;
    result.values.forEach((entry,i)=>{
      const box=node('div'),label=node('label',entry.value||'(blank status)'),select=node('select');
      select.id=`status-map-${i}`;select.dataset.rawStatus=entry.value;select.required=true;label.htmlFor=select.id;
      [['','Choose how to count this status'],['completed','Completed — count sale and refund'],['cancelled','Cancelled — zero revenue']].forEach(([value,text])=>{const option=node('option',text);option.value=value;select.append(option);});
      select.value=entry.suggested;select.addEventListener('change',invalidateUpload);box.append(label,select);$('upload-status-matches').append(box);
    });
    $('validate-upload').disabled=uploadState.busy;
  }catch(e){if(version===uploadState.statusVersion){uploadError(e.message);$('validate-upload').disabled=true;}}
}
function readFile(file) {
  return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(new Error('The file could not be read. Choose it again.'));reader.readAsDataURL(file);});
}
async function inspectUpload(sheet) {
  if(!uploadState.file||uploadState.busy)return;
  uploadError(null);uploadBusy(true,'Reading your spreadsheet...');
  try {
    uploadState.content=uploadState.content||await readFile(uploadState.file);
    const data=await api('/api/import/inspect',{filename:uploadState.file.name,content:uploadState.content,...(sheet?{sheet}:{})});
    uploadState.inspected=data;uploadState.preview=null;
    $('upload-file-title').textContent=data.filename;$('upload-row-count').textContent=`${data.row_count.toLocaleString()} orders found · First five rows shown`;
    $('sheet-picker').hidden=data.sheets.length===1;$('upload-sheet').replaceChildren(...data.sheets.map(name=>{const option=node('option',name);option.value=name;return option;}));$('upload-sheet').value=data.sheet;
    table($('upload-source-preview'),data.headers,data.preview.map(r=>r.values));
    $('upload-column-matches').replaceChildren();
    data.fields.forEach(field=>{
      const box=node('div'),label=node('label',field.label+(field.required?' *':'')),select=node('select');select.id=`map-${field.key}`;select.required=field.required;label.htmlFor=select.id;
      const empty=node('option',field.required?'Choose a column':'Not in my file');empty.value='';select.append(empty);
      data.headers.forEach(header=>{const option=node('option',header);option.value=header;select.append(option);});select.value=data.mapping[field.key];
      select.addEventListener('change',()=>{invalidateUpload();if(field.key==='status')statusMatches();});box.append(label,select);$('upload-column-matches').append(box);
    });
    $('upload-currency').replaceChildren(...data.currencies.map(code=>{const option=node('option',code);option.value=code;return option;}));
    $('upload-grain-confirm').checked=false;$('upload-defaults-confirm').checked=false;uploadStep(2);updateAssumptions();
    $('upload-message').textContent='Check the column matches. Nothing has been imported yet.';
  }catch(e){uploadError(e.message);}finally{uploadBusy(false,$('upload-error').hidden?'Check the column matches. Nothing has been imported yet.':'');}
  if(uploadState.inspected&&$('upload-error').hidden)await statusMatches();
}
$('open-import').addEventListener('click',()=>showView('import-view'));
$('orders-file').addEventListener('change',()=>{
  if(uploadState.busy)return;
  uploadState.file=$('orders-file').files[0]||null;uploadState.content=null;uploadState.inspected=null;uploadState.preview=null;uploadError(null);
  if(uploadState.file&&(!/\.(csv|xlsx)$/i.test(uploadState.file.name)||uploadState.file.size>2*1024*1024||!uploadState.file.size)){
    uploadError('Choose a non-empty CSV or XLSX file no larger than 2 MB.');uploadState.file=null;
  }
  $('inspect-upload').disabled=!uploadState.file;
});
$('inspect-upload').addEventListener('click',()=>inspectUpload());
$('upload-sheet').addEventListener('change',()=>inspectUpload($('upload-sheet').value));
['upload-shop-name','upload-currency','upload-date-format','upload-number-format'].forEach(id=>$(id).addEventListener('input',invalidateUpload));
$('upload-start-over').addEventListener('click',async()=>{
  if(uploadState.busy)return;uploadBusy(true,'Clearing the upload preview...');
  try{await api('/api/import/cancel',{});uploadState.inspected=null;uploadState.preview=null;uploadState.content=null;uploadStep(1);uploadError(null);}catch(e){uploadError(e.message);}finally{uploadBusy(false);}
});
$('upload-mapping-form').addEventListener('submit',async event=>{
  event.preventDefault();if(uploadState.busy||!uploadState.inspected)return;uploadError(null);uploadBusy(true,'Checking every order...');uploadState.preview=null;
  const statusMap=Object.fromEntries([...$('upload-status-matches').querySelectorAll('select')].map(e=>[e.dataset.rawStatus,e.value]));
  try {
    const preview=await api('/api/import/validate',{upload_id:uploadState.inspected.upload_id,mapping:mappingValues(),options:{shop_name:$('upload-shop-name').value,currency:$('upload-currency').value,date_format:$('upload-date-format').value,decimal_mark:$('upload-number-format').value,status_map:statusMap,one_row_per_order:$('upload-grain-confirm').checked,confirm_defaults:$('upload-defaults-confirm').checked}});
    if(!preview.valid){uploadError(`${preview.error_count} ${preview.error_count===1?'row needs':'rows need'} attention. No orders were imported.\n`+preview.errors.map(e=>`Row ${e.row}: ${e.message}`).join('\n'));return;}
    uploadState.preview=preview;
    const d=preview.dataset,format=n=>n===null?'Not defined':new Intl.NumberFormat('en-US',{style:'currency',currency:d.currency,maximumFractionDigits:2}).format(n);
    $('upload-summary').textContent=`${d.shop_name} · ${d.order_count.toLocaleString()} orders · ${d.customer_count===null?'Customer identities unavailable':d.customer_count+' customers'} · ${d.start} to ${d.end} · ${d.currency}`;
    table($('upload-totals'),['Metric','Checked total'],[['Net revenue',format(preview.metrics.net_revenue)],['Completed orders',preview.metrics.completed_orders],['Average order value',format(preview.metrics.average_order_value)],['Refund rate',preview.metrics.refund_rate_pct===null?'Not defined':preview.metrics.refund_rate_pct+'%']]);
    $('upload-review-warnings').replaceChildren(...d.warnings.map(text=>node('li',text)));
    table($('upload-normalized-preview'),['order ID','customer ID','date','channel','status','gross amount','refund amount'],preview.sample);uploadStep(3);
  }catch(e){uploadError(e.message);}finally{uploadBusy(false,uploadState.preview?'Your data passed the checks. Compare the totals before importing.':'');}
});
$('upload-edit-mapping').addEventListener('click',()=>{invalidateUpload();uploadStep(2);});
$('commit-upload').addEventListener('click',async()=>{
  if(uploadState.busy||!uploadState.preview)return;uploadError(null);uploadBusy(true,'Preparing your shop workspace...');
  try {
    const data=await api('/api/import/commit',{upload_id:uploadState.inspected.upload_id,preview_id:uploadState.preview.preview_id});
    uploadState.inspected=null;uploadState.preview=null;uploadState.content=null;uploadState.file=null;$('orders-file').value='';applyWorkspace(data);uploadStep(1);showView('workspace');
  }catch(e){uploadError(e.message);}finally{uploadBusy(false,state.dataset?.kind==='upload'?'Your shop is ready. Explore your numbers or upload a replacement sheet.':'');}
});
$('reset-upload').addEventListener('click',async()=>{
  if(uploadState.busy)return;uploadError(null);uploadBusy(true,'Removing the temporary shop data...');
  try{const data=await api('/api/import/reset',{});uploadState.inspected=null;uploadState.preview=null;uploadState.content=null;uploadState.file=null;$('orders-file').value='';applyWorkspace(data);uploadStep(1);showView('workspace');}catch(e){uploadError(e.message);}finally{uploadBusy(false);}
});
$('upload-open-workspace').addEventListener('click',()=>showView('workspace'));
uploadStep(1);
