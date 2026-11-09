'use strict';
const $=id=>document.getElementById(id);
const money=new Intl.NumberFormat('en',{notation:'compact',maximumFractionDigits:2});
const n2=new Intl.NumberFormat('en',{maximumFractionDigits:2});
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const safeUrl=x=>typeof x==='string'&&/^https:\/\//i.test(x)?esc(x):'#';
const pct=x=>Number.isFinite(x)?(x>0?'+':'')+n2.format(100*x)+'%':'—';
const usd=x=>Number.isFinite(x)?(x<0?'−$':'$')+money.format(Math.abs(x)):'—';
const label=x=>({reit:'REIT',holdco:'Holding company',bank:'Bank / lender',broker:'Broker',insurer:'Insurance',operating:'Operating company',cyclical:'Cyclical',commodity:'Commodity',utility:'Utility',unknown:'Unclassified'}[x]||x);
const best=r=>r.models?.decisions?.find(x=>x.method===r.models.selected);
const fieldNames={sales:'Revenue',net:'Net income',ebit:'Operating profit',book:'Parent equity',cash:'Cash and equivalents',cfo:'Operating cash flow',capex:'Cash capital investment',div:'Cash dividends',assets:'Total assets',liabilities:'Total liabilities'};
const field=x=>fieldNames[x]||x.replaceAll('_',' ');
let snapshot=null,page=0,visible=[];
const size=25;

function setData(data) {
 if(!data || !Array.isArray(data.rows) || !data.stats || !['private_market','public_fundamentals'].includes(data.mode) || data.rows.some(r=>typeof r.symbol!=='string'||typeof r.name!=='string')) throw Error('This file is not an Equity Atlas snapshot.');
 snapshot=data;page=0;
 const market=data.mode==='private_market', s=data.stats;
 $('edition').textContent=(market?'MARKET SNAPSHOT':'PUBLIC FILINGS')+'  /  '+data.as_of;
 $('subtitle').textContent=market?'Compare market prices, financial statements, and CFA valuation scenarios by business type.':'Explore annual filings and financial history. Open a locally generated snapshot to compare market valuations.';
 $('stamp').textContent='Rules '+data.policy_version+' · '+data.as_of;
 const tiles=market?[['Companies',s.issuers,'One row per issuer'],['Recent statements',s.fresh,'Within 465 days of snapshot'],['Lead valuations',s.selected,'Passed model checks'],['Cycle reads',s.normalized,'Operating margin vs. prior years']]:[['Companies',s.issuers,'SEC filing universe'],['Recent statements',s.fresh,'Within 465 days'],['Market data','Local','Open your own snapshot'],['Source','SEC','Company Facts']];
 $('metrics').innerHTML=tiles.map(([t,v,h])=>'<div class="metric"><small>'+esc(t)+'</small><strong>'+esc(v)+'</strong><small class="hint">'+esc(h)+'</small></div>').join('');
 const kinds=[...new Set(data.rows.map(r=>r.kind))].sort((a,b)=>label(a).localeCompare(label(b)));
 $('kind').innerHTML='<option value="">All business types</option>'+kinds.map(k=>'<option value="'+esc(k)+'">'+esc(label(k))+'</option>').join('');
 $('order').innerHTML=market?'<option value="rank">Market cap</option><option value="name">Company name</option><option value="gap">Lead model gap</option>':'<option value="name">Company name</option><option value="new">Latest fiscal period</option>';
 $('coverage').querySelector('[value="valued"]').hidden=!market;
 $('segment-label').hidden=!market;
 $('segment-label').parentElement.classList.toggle('market',market);
 clearFilters();
}
function isFresh(r) {
 return r.fresh??(r.statement&&((Date.parse(snapshot.as_of)-Date.parse(r.statement.end))/86400000)<=465);
}
function clearFilters() {
 $('search').value='';$('kind').value='';$('coverage').value='';$('segment').value='';$('order').selectedIndex=0;page=0;render();
}
function render() {
 if(!snapshot)return;
 const market=snapshot.mode==='private_market';
 const query=$('search').value.toLowerCase().trim(),kind=$('kind').value,cov=$('coverage').value,order=$('order').value,segment=$('segment').value;
 const segmentPass=r=>!segment||({loss:r.earnings_state==='loss',dividends:r.dividend_state==='stable payer',
  peak:r.cycle?.phase==='above historical range',trough:r.cycle?.phase==='below historical range',
  high_growth:r.growth_state==='high historical growth'}[segment]);
 visible=snapshot.rows.filter(r=>segmentPass(r)&&(!kind||r.kind===kind)&&(!query||[r.name,r.symbol,r.country,r.peer_group].join(' ').toLowerCase().includes(query))&&(!cov||(cov==='fresh'&&isFresh(r))||(cov==='missing'&&!isFresh(r))||(cov==='valued'&&best(r))));
 visible.sort((a,b)=>order==='gap'?((best(b)?.gap??-Infinity)-(best(a)?.gap??-Infinity)||a.rank-b.rank):order==='rank'?a.rank-b.rank:order==='new'?(b.statement?.end??'').localeCompare(a.statement?.end??'')||a.name.localeCompare(b.name):a.name.localeCompare(b.name));
 const titles=market?['#','Company','Business','Market cap','Fiscal end','Cycle position','Lead valuation','Gap']:['Company','Business','Accounting','Fiscal end','Revenue','Net income','Filing'];
 $('head').innerHTML='<tr>'+titles.map(t=>'<th scope="col">'+t+'</th>').join('')+'</tr>';
 const start=page*size;
 $('body').innerHTML=visible.slice(start,start+size).map((r,i)=>{
   const m=best(r),st=r.statement, symbol='<button type="button" class="company" data-row="'+(start+i)+'">'+esc(r.name)+'</button><span class="symbol">'+esc(r.symbol)+(r.country?' · '+esc(r.country):'')+'</span>';
   const period=st?'<span class="'+(isFresh(r)?'minor':'pill warn')+'">'+esc(st.end)+'</span>':'<span class="pill warn">Missing</span>';
   const curr=st?.currency||'';
   const reported=k=>Number.isFinite(st?.facts?.[k]?.value)?esc(curr)+' '+money.format(st.facts[k].value):'—';
   const cells=market?[esc(r.rank),symbol,esc(label(r.kind)),usd(r.market_cap_usd),period,esc(r.cycle?.phase==='not classified cyclical'?'—':r.cycle?.phase),m?esc(m.label):'<span class="minor">No lead estimate</span>',m?'<span class="'+(m.gap>=0?'up':'down')+'">'+pct(m.gap)+'</span>':'—']:[symbol,esc(label(r.kind)),esc(r.accounting||'—'),period,reported('sales'),reported('net'),st?'<span class="pill">EDGAR</span>':'—'];
   return '<tr>'+cells.map(t=>'<td>'+t+'</td>').join('')+'</tr>';
 }).join('')||'<tr><td class="empty" colspan="'+titles.length+'">No companies match these filters.</td></tr>';
 $('scope').textContent=visible.length+' of '+snapshot.rows.length+' companies'+(market?' · USD market caps':' · SEC company facts');
 $('paging').textContent=visible.length?(start+1)+'–'+Math.min(start+size,visible.length)+' of '+visible.length:'0 results';
 $('prev').disabled=page===0;$('next').disabled=start+size>=visible.length;
}
function detail(r) {
 const st=r.statement,m=best(r),cycle=r.cycle||{}, curr=st?.currency??'';
 const percentInputs=new Set(['re','g','roe','wacc','payout','terminal_roic','terminal_roe','tax','capex_sales','da_sales','nwc_sales_proxy','growth_start','ebit_margin','target_margin','fcfe_sales','market_implied_dividend_growth','market_implied_terminal_ebit_margin','market_implied_roe']);
 const dl=obj=>'<dl class="fields">'+Object.entries(obj).map(([k,v])=>'<dt>'+esc(field(k))+'</dt><dd>'+esc(Array.isArray(v)?v.map(x=>typeof x==='number'?n2.format(x):x).join(', '):typeof v==='number'?(percentInputs.has(k)?pct(v):n2.format(v)):v)+'</dd>').join('')+'</dl>';
 const sources=st?Object.entries(st.facts).map(([k,v])=>'<tr><td>'+esc(field(k))+'</td><td>'+esc(curr)+' '+n2.format(v.value)+'</td><td><a target="_blank" rel="noopener noreferrer" href="'+safeUrl(v.url)+'">'+esc(v.form||'Filing')+' · '+esc(v.filed)+'</a><br><span class="minor">'+esc(v.locator||v.tag)+'</span></td></tr>').join(''):'';
 const margins=(r.history||[]).flatMap(h=>h.facts.sales?.value>0&&Number.isFinite(h.facts.ebit?.value)?[[h.end.slice(0,4),h.facts.ebit.value/h.facts.sales.value]]:[]);
 const max=Math.max(.1,...margins.map(x=>Math.abs(x[1])));
 const chart=margins.length>=2?'<h3>Reported operating margin</h3><div class="spark" aria-label="Fiscal-year operating margins">'+margins.map(([y,v])=>'<div class="'+(v<0?'negative':'')+'"><span>'+pct(v)+'</span><b style="height:'+Math.max(2,Math.abs(v)*70/max)+'px"></b><span>'+esc(y)+'</span></div>').join('')+'</div>':'';
 const decisions=r.models?'<h3>Valuation decisions</h3>'+r.models.decisions.map(x=>'<details><summary><strong>'+esc(x.label)+'</strong> · '+(x.status==='estimated'?usd(x.equity_usd)+' ('+pct(x.gap)+')':esc(x.status.replaceAll('_',' ')))+'</summary><p>'+esc(x.reason)+'</p>'+(x.status==='estimated'?'<p>Range: '+usd(x.low_usd)+' to '+usd(x.high_usd)+'</p>'+dl(x.inputs)+(x.cycle_cases_usd?'<p>Cycle scenarios</p>'+dl(x.cycle_cases_usd):''):'')+'</details>').join(''):'';
 const ratios=Object.entries(r.ratios||{}).map(([k,v])=>'<dt>'+esc(k)+'</dt><dd>'+n2.format(v.multiple)+'×</dd>').join('');
 $('detail-title').textContent=r.name+' · '+r.symbol;
 $('content').innerHTML='<p class="lede">'+esc(label(r.kind))+' · '+esc(r.peer_group)+' · '+esc(r.classification)+'</p>'+
   (m?'<div class="notice">Lead model: '+esc(m.label)+' · '+usd(m.equity_usd)+' · '+pct(m.gap)+' vs. market cap</div>':'')+
   (ratios?'<h3>Observed multiples</h3><dl class="fields">'+ratios+'</dl>':'')+chart+
   (cycle.mid_margin!==undefined?'<p>Cycle: '+esc(cycle.phase)+' · current '+pct(cycle.actual_margin)+' vs. historical median '+pct(cycle.mid_margin)+' · '+esc(cycle.window.join(' to '))+'</p>':'')+
   decisions+'<h3>Annual filing evidence</h3>'+(sources?'<p>Fiscal year ended '+esc(st.end)+' · '+esc(r.accounting)+' · '+esc(r.source)+'</p><div class="tablewrap"><table><thead><tr><th scope="col">Metric</th><th scope="col">Amount</th><th scope="col">Filing and concept</th></tr></thead><tbody>'+sources+'</tbody></table></div>':'<p>No qualifying annual statement.</p>')+
   ((r.issues||[]).length?'<h3>Data gaps</h3><ul>'+r.issues.map(x=>'<li>'+esc(x)+'</li>').join('')+'</ul>':'');
 $('detail').showModal();
}
$('methodology').addEventListener('click',()=>{
 $('detail-title').textContent='Methodology';
 $('content').innerHTML='<p class="lede">Start with the economics of the issuer. Match the method to the business, then require evidence for the denominator and the forecast.</p><h3>Routing</h3><p>Banks and insurers use common book, residual income and matching peers. Operating companies start with FCFF. Stable dividends support DDM. Losses rule out positive earnings multiples; holding companies need supported fair-value NAV.</p><h3>Cycle view</h3><p>Compare the latest operating margin with at least five preceding comparable annual margins. Quartiles and the median anchor trough, midcycle and strong operating scenarios. These are historical positions, not forecasts of the macro cycle.</p><h3>Reading the numbers</h3><p>Model estimates depend on assumptions. Discount and growth sensitivity is not a probability interval. Lead model gaps across different model types are not directly comparable. A missing or stale input blocks the affected output.</p><h3>Sources</h3><p><a href="https://www.sec.gov/search-filings/edgar-application-programming-interfaces" target="_blank" rel="noopener noreferrer">SEC EDGAR Company Facts</a> and <a href="https://filings.xbrl.org/" target="_blank" rel="noopener noreferrer">XBRL International filings</a>. A locally opened market snapshot stays in this browser tab and is not uploaded.</p>';
 $('detail').showModal();
});
$('close').addEventListener('click',()=>$('detail').close());
$('body').addEventListener('click',e=>{const button=e.target.closest('[data-row]');if(button)detail(visible[Number(button.dataset.row)]);});
for(const id of ['search','kind','coverage','segment','order'])$(id).addEventListener(id==='search'?'input':'change',()=>{page=0;render();});
$('reset').addEventListener('click',clearFilters);
$('prev').addEventListener('click',()=>{page--;render();});
$('next').addEventListener('click',()=>{page++;render();});
$('load').addEventListener('change',async e=>{
 const file=e.target.files[0];if(!file)return;
 try{setData(JSON.parse(await file.text()));}catch(err){$('scope').textContent=err.message;}
 e.target.value='';
});
fetch('snapshot.json').then(r=>{if(!r.ok)throw Error('No bundled snapshot');return r.json();}).then(setData).catch(()=>{
 if(!snapshot)$('scope').textContent='Open a snapshot JSON to start. Serve this folder over HTTP to load its bundled snapshot automatically.';
});
