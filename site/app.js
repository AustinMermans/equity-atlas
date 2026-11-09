'use strict';
const $=id=>document.getElementById(id);
const money=new Intl.NumberFormat('en',{notation:'compact',maximumFractionDigits:2});
const n2=new Intl.NumberFormat('en',{maximumFractionDigits:2});
const reportedAmount=new Intl.NumberFormat('en',{maximumFractionDigits:10});
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const safeUrl=x=>typeof x==='string'&&/^https:\/\//i.test(x)?esc(x):'#';
const pct=x=>Number.isFinite(x)?(x>0?'+':'')+n2.format(100*x)+'%':'—';
const usd=x=>Number.isFinite(x)?(x<0?'−$':'$')+money.format(Math.abs(x)):'—';
const label=x=>({reit:'REIT',holdco:'Holding company',bank:'Bank / lender',broker:'Broker',insurer:'Insurance',operating:'Operating company',cyclical:'Cyclical',commodity:'Commodity',utility:'Utility',unknown:'Unclassified'}[x]||x);
const best=r=>r.models?.decisions?.find(x=>x.method===r.models.selected);
const fieldNames={
 other_income_expense_note:'Other income and expense (expense sign)',
 derivative_gain_loss_note:'Derivative gains and losses (expense sign)',
 amortization_purchased_intangibles_with_impairment:'Purchased intangible amortization and impairment',
 amortization_finance_rou:'Amortization of finance lease assets',
 da_ppe_and_rou:'PP&E depreciation and right-of-use asset amortization',
 da_including_operating_rou:'D&A including operating lease asset amortization',
 impairment_intangible_net:'Intangible asset impairment net of reversals',
 impairment_ppe_and_exploration:'Exceptional PP&E impairments and capitalized exploration charges',
 impairment_intangibles_and_goodwill:'Exceptional impairment of intangible assets including goodwill',
 impairment_goodwill:'Goodwill impairment',
 insurance_revenue:'Insurance revenue',
 sales_adjusted:'Adjusted revenue (non-GAAP)',
 costs_adjusted:'Adjusted costs (non-GAAP)',
 other_income_adjusted:'Adjusted other income (non-GAAP)',
 ebit_adjusted:'Adjusted operating profit (non-GAAP)',
 impairment_ppe_net:'Owned PP&E impairment net of reversals',
 capex_net_of_disposals:'Cash capital purchases net of disposals',
 capex_disposal_proceeds:'Cash proceeds from disposals of productive assets',
 depreciation_other_assets:'Depreciation of other assets',
 da_excluding_acquired_intangibles:'D&A excluding acquired intangible amortization',
 amortization_operating_rou:'Amortization of operating lease assets',
 depreciation_leased_assets:'Depreciation on assets leased to customers',
 capex_intangibles_discontinued:'Cash intangible purchases by discontinued operations',
 capex_intangibles_continuing:'Cash intangible purchases by continuing operations',
 capex_exploration_capitalized:'Capitalized exploration and evaluation cash spending',
 exploration_evaluation_spending:'Total exploration and evaluation cash spending',
 exploration_evaluation_expensed:'Exploration cash spending included in operating cash flow',
 capex_ppe:'Cash purchases of property, plant and equipment',
 capex_intangibles:'Cash purchases of intangible assets',
 capex_mixed_outflow:'Combined investing outflow with an unallocated asset component',
 capex_financing_payment:'Financing cash paid on previously acquired assets',
 da_with_writeoffs:'Depreciation, amortization and write-offs',
 da_with_impairment_and_writeoffs:'Depreciation, amortization, net impairments and exploration write-offs',
 da_including_nonoperating:'Cash-flow D&A including nonoperating amounts',
 da_including_content:'Total D&A including content amortization',
 amortization_content:'Content asset amortization',
 amortization_purchased_intangibles:'Amortization of purchased intangible assets',
 client_funds_interest_expense:'Interest expense tied to the client-funds strategy',
 client_funds_interest_income_corporate:'Corporate interest income tied to the client-funds strategy',
 corporate_interest_expense_other:'Corporate interest expense outside the client-funds strategy',
 corporate_interest_income_other:'Corporate interest income outside the client-funds strategy',
 corporate_interest_income_filed:'Total interest income on corporate funds',
 nonoperating_income_net:'Filed other income, net',
 ibm_segment_profit_bridge:'IBM pretax income reconciled to reportable segment profit',
 ibm_segment_profit_note:'IBM profit across all reportable segments',
 ibm_debt_split_note:'IBM total debt by business scope',
 ibm_reportable_segment_profit:'IBM reported segment profit before unallocated items',
 ibm_net_interest_ex_financing:'Net interest income or expense outside IBM Financing',
 ibm_nonoperating_retirement_income:'IBM nonoperating retirement income or expense',
 ibm_software_segment_profit:'Software segment profit',
 ibm_consulting_segment_profit:'Consulting segment profit',
 ibm_infrastructure_segment_profit:'Infrastructure segment profit',
 ibm_financing_segment_profit:'IBM Financing segment profit including intercompany activity',
 ibm_financing_debt:'IBM Financing debt allocation',
 ibm_nonfinancing_debt:'IBM non-Financing debt allocation',
 runoff_insurance_costs:'Run-off insurance costs and expenses',
 runoff_insurance_operating_profit:'Run-off insurance operating profit',
 runoff_insurance_pretax_income:'Run-off insurance pretax income',
 runoff_insurance_tax_effect:'Run-off insurance tax effect',
 ge_insurance_income_note:'Run-off insurance after-tax net income',
 ebit_equipment_segments:'Operating profit across equipment segments',
 ebit_financial_services_segment:'Financial Services segment operating profit after interest',
 ebit_reported_segment_total:'Reported operating profit across all segments',
 pretax_equipment_operations:'Equipment Operations pretax income',
 pretax_financial_services:'Financial Services pretax income',
 net_equipment_operations:'Equipment Operations net income attributable to Deere',
 net_financial_services:'Financial Services net income',
 cfo_equipment_operations:'Equipment Operations cash flow from operations',
 cfo_financial_services:'Financial Services cash flow from operations',
 distributions_from_financial_services:'Distributions from Financial Services to Equipment Operations',
 cfo_equipment_before_finance_distributions:'Equipment Operations cash flow before Financial Services distributions',
 da_equipment_operations:'Equipment Operations D&A',
 da_financial_services:'Financial Services D&A',
 capex_ppe_equipment_operations:'Equipment Operations PP&E purchases',
 capex_ppe_financial_services:'Financial Services PP&E purchases',
 operating_lease_equipment_purchases_financial_services:'Financial Services purchases of equipment for operating leases',
 operating_lease_equipment_sales_financial_services:'Financial Services proceeds from equipment on operating leases',
 assets_equipment_operations:'Equipment Operations assets',
 assets_financial_services:'Financial Services assets',
 equity_equipment_operations_adjusted:'Equipment Operations adjusted total equity',
 equity_financial_services:'Financial Services equity',
 sales:'Revenue',sales_unreconciled:'Reported revenue pending scope review',capex_unreconciled:'Reported cash investment pending scope review',sales_and_other_income:'Total revenue and other income',sales_before_excise:'Sales before excise taxes',excise_taxes_on_sales:'Excise taxes on sales',other_revenues:'Other revenues',net:'Earnings used by Atlas',net_common:'Earnings available to common',net_eps_basic:'Income allocated to basic EPS',net_eps_diluted:'Income allocated to diluted EPS',cfo_continuing:'Operating cash flow from continuing operations',net_continuing:'Net income from continuing operations',net_parent_continuing:'Parent net income from continuing operations',net_discontinued:'Net income from discontinued operations',dividend_in_kind:'Noncash distribution to shareholders',eps_ads_basic:'Basic earnings per ADS',eps_ads_diluted:'Diluted earnings per ADS',net_nci:'Net income attributable to noncontrolling interests',net_nonredeemable_nci:'Net income attributable to nonredeemable noncontrolling interests',temporary_equity_total:'Total temporary equity carrying value',temporary_equity_parent:'Parent temporary equity carrying value',redeemable_nci:'Redeemable noncontrolling interests carrying value',redeemable_nci_cips:'Redeemable NCI in consolidated sponsored investment products',redeemable_nci_subco:'Redeemable NCI in Subco',hybrid_equity:'Equity-classified perpetual hybrid bonds',minority:'Permanent noncontrolling interests',minority_consolidated_entities:'Permanent NCI in consolidated entities',minority_holdings:'Permanent NCI in Blackstone Holdings',redeemable_nci_redemption:'Redeemable noncontrolling interests redemption value',net_parent:'Net income attributable to parent',net_consolidated:'Consolidated net income',common_book:'Common shareholders’ equity',preferred:'Preferred carrying value',preferred_liquidation:'Preferred liquidation preference',contract_sales:'Contract revenue',div_total:'Total cash dividends paid',div_common_declared:'Common cash dividends declared',da:'Depreciation and amortization',da_with_impairment:'Depreciation, amortization and impairment',da_with_other:'Depreciation, amortization and other adjustments',da_tagged_component:'Tagged D&A with partial scope',da_ppe:'Property and equipment D&A',ppe_da_with_impairment:'Property and equipment depreciation and impairment',amortization_with_impairment:'Software and intangible amortization and impairment',depreciation_ppe_and_software:'Property, equipment and software depreciation',impairment_ppe_and_software:'Property, equipment and software impairment',da_with_rou_and_impairment:'Cash-flow D&A including right-of-use amortization and impairment',ppe_da_with_impairment_and_lease:'Property depreciation, impairment and land-use lease costs',asset_transaction_gain:'Gain on acquisitions, disposition and remeasurement',retirement_accretion:'Asset retirement obligation accretion',risk_management_net_gain:'Risk management net gain or loss',foreign_exchange_net_gain:'Foreign exchange net gain or loss',da_ppe_and_finance_lease:'PP&E depreciation and finance lease amortization',da_general_and_administrative:'General and administrative D&A',da_cost_of_sales:'D&A in cost of sales',da_reported_total:'Reported D&A reconciliation total',amortization_with_rou:'Amortization of intangible and right-of-use assets',amortization_with_other_assets:'Amortization of intangible and other assets',depreciation_with_disposal_loss:'Depreciation and loss on disposal',amortization_deferred_contract_costs:'Amortization of deferred contract costs',amortization_deferred_transition:'Amortization of deferred transition costs',other_da_adjustment:'Other D&A reconciliation adjustment',da_excluding_nuclear_fuel:'Depreciation and amortization excluding nuclear fuel',da_with_accretion:'Cash-flow D&A and related items',div_nci:'Cash distributions to noncontrolling interests',ebit:'Operating profit',book:'Parent equity',cash:'Cash and equivalents',cfo:'Operating cash flow',capex:'Cash capital investment',capex_reported_total:'Company-reported total cash capex',div:'Cash dividends',assets:'Total assets',liabilities:'Total liabilities'};
const field=x=>fieldNames[x]||x.replaceAll('_',' ');
let snapshot=null,page=0,visible=[];
const size=25;

function setData(data) {
 if(!data || !Array.isArray(data.rows) || !data.stats || !['private_market','public_fundamentals','public_market'].includes(data.mode) || data.rows.some(r=>typeof r.symbol!=='string'||typeof r.name!=='string')) throw Error('This file is not an Equity Atlas snapshot.');
 snapshot=data;page=0;
 const market=data.mode==='private_market', openMarket=data.mode==='public_market', s=data.stats;
 $('edition').textContent=(openMarket?'PUBLIC MARKET DATA':market?'MARKET SNAPSHOT':'PUBLIC FILINGS')+'  /  '+data.as_of;
 $('subtitle').textContent=openMarket?'Taiwan exchange closes and valuation multiples alongside source-linked EDGAR filings.':market?'Compare market prices, financial statements, and CFA valuation scenarios by business type.':'Explore annual filings and financial history. Open a locally generated snapshot to compare market valuations.';
 $('stamp').textContent='Rules '+data.policy_version+' · '+data.as_of;
 $('attribution').innerHTML=openMarket?'<a href="https://data.gov.tw/en/license">Taiwan Stock Exchange and Financial Supervisory Commission · Open Government Data License 1.0</a> · <a href="https://www.cbc.gov.tw/en/cp-510-1865-DA249-2.html">Central Bank of Taiwan FX</a>':'';
 const tiles=openMarket?[['Exchange prices',s.priced,'Taiwan close · '+data.market_sources.date],['SEC issuers',s.sec_issuers,'EDGAR issuer coverage'],['Latest annual covered',(s.latest_annual_extracted+(s.latest_annual_issuer_mirror??0)+(s.latest_annual_regulator_mirror??0)+(s.latest_annual_sec_workbook??0))+' / '+s.latest_annual_expected,s.latest_annual_extracted+' direct SEC · '+((s.latest_annual_issuer_mirror??0)+(s.latest_annual_regulator_mirror??0))+' public 20-F copies · '+(s.latest_annual_sec_workbook??0)+' SEC workbooks'],['Latest quarters',s.interim_expected?s.interim_available+' / '+s.interim_expected:s.interim_available,'Standalone quarter data']]:market?[['Companies',s.issuers,'One row per issuer'],['Recent statements',s.fresh,'Within 465 days of snapshot'],['Lead valuations',s.selected,'Passed model checks'],['Cycle reads',s.normalized,'Operating margin vs. prior years']]:[['Companies',s.issuers,'SEC filing universe'],['Recent statements',s.fresh,'Within 465 days'],['Market data','Local','Open your own snapshot'],['Source','SEC','Company Facts']];
 $('metrics').innerHTML=tiles.map(([t,v,h])=>'<div class="metric"><small>'+esc(t)+'</small><strong>'+esc(v)+'</strong><small class="hint">'+esc(h)+'</small></div>').join('');
 const kinds=[...new Set(data.rows.map(r=>r.kind))].sort((a,b)=>label(a).localeCompare(label(b)));
 $('kind').innerHTML='<option value="">All business types</option>'+kinds.map(k=>'<option value="'+esc(k)+'">'+esc(label(k))+'</option>').join('');
 $('order').innerHTML=openMarket?'<option value="exchange">Taiwan market cap</option><option value="name">Company name</option><option value="new">Latest fiscal year</option>':market?'<option value="rank">Market cap</option><option value="name">Company name</option><option value="gap">Lead model gap</option>':'<option value="name">Company name</option><option value="new">Latest fiscal period</option>';
 $('coverage').querySelector('[value="valued"]').hidden=!(market||openMarket);
 $('coverage').querySelector('[value="priced"]').hidden=!openMarket;
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
 const market=snapshot.mode==='private_market', openMarket=snapshot.mode==='public_market';
 const query=$('search').value.toLowerCase().trim(),kind=$('kind').value,cov=$('coverage').value,order=$('order').value,segment=$('segment').value;
 const segmentPass=r=>!segment||({loss:r.earnings_state==='loss',dividends:r.dividend_state==='stable payer',
  peak:r.cycle?.phase==='above historical range',trough:r.cycle?.phase==='below historical range',
  high_growth:r.growth_state==='high historical growth'}[segment]);
 visible=snapshot.rows.filter(r=>segmentPass(r)&&(!kind||r.kind===kind)&&(!query||[r.name,r.symbol,r.country,r.peer_group,r.market?.code,r.market?.local_name].join(' ').toLowerCase().includes(query))&&(!cov||(cov==='fresh'&&isFresh(r))||(cov==='missing'&&!isFresh(r))||(cov==='valued'&&best(r))||(cov==='priced'&&r.market)));
 visible.sort((a,b)=>order==='exchange'?((a.market?.rank??Infinity)-(b.market?.rank??Infinity)||a.name.localeCompare(b.name)):order==='gap'?((best(b)?.gap??-Infinity)-(best(a)?.gap??-Infinity)||a.rank-b.rank):order==='rank'?a.rank-b.rank:order==='new'?(b.statement?.end??'').localeCompare(a.statement?.end??'')||a.name.localeCompare(b.name):a.name.localeCompare(b.name));
 const titles=openMarket?['Company','TWSE close','Est. equity cap','P/E · TWSE','P/B · TWSE','Fiscal year','Revenue','Earnings','Interim']:market?['#','Company','Business','Market cap','Fiscal end','Cycle position','Lead valuation','Gap']:['Company','Business','Accounting','Fiscal end','Revenue','Net income','Filing'];
 $('head').innerHTML='<tr>'+titles.map(t=>'<th scope="col">'+t+'</th>').join('')+'</tr>';
 const start=page*size;
 $('body').innerHTML=visible.slice(start,start+size).map((r,i)=>{
   const m=best(r),st=r.statement, symbol='<button type="button" class="company" data-row="'+(start+i)+'">'+esc(r.name)+'</button><span class="symbol">'+esc(r.symbol)+(r.country?' · '+esc(r.country):'')+'</span>';
   const period=st?'<span class="'+(isFresh(r)?'minor':'pill warn')+'">'+esc(st.end)+'</span>':'<span class="pill warn">Missing</span>';
   const curr=st?.currency||'';
   const reported=k=>Number.isFinite(st?.facts?.[k]?.value)?esc(curr)+' '+money.format(st.facts[k].value):'—';
   const q=r.market;
   const quoteMultiple=key=>Number.isFinite(q?.exchange_multiples?.[key])?n2.format(q.exchange_multiples[key])+'×':'—';
   const cells=openMarket?[symbol,q?'NT$'+n2.format(q.close):'—',q?'NT$'+money.format(q.estimated_cap_twd):'—',quoteMultiple('P/E'),quoteMultiple('P/B'),period,reported('sales'),reported('net'),esc(r.edgar?.quarter?.end||r.edgar?.ytd?.end||'—')]:market?[esc(r.rank),symbol,esc(label(r.kind)),usd(r.market_cap_usd),period,esc(r.cycle?.phase==='not classified cyclical'?'—':r.cycle?.phase),m?esc(m.label):'<span class="minor">No lead estimate</span>',m?'<span class="'+(m.gap>=0?'up':'down')+'">'+pct(m.gap)+'</span>':'—']:[symbol,esc(label(r.kind)),esc(r.accounting||'—'),period,reported('sales'),reported('net'),st?'<span class="pill">'+esc(r.source)+'</span>':'—'];
   return '<tr>'+cells.map(t=>'<td>'+t+'</td>').join('')+'</tr>';
 }).join('')||'<tr><td class="empty" colspan="'+titles.length+'">No companies match these filters.</td></tr>';
 $('scope').textContent=visible.length+' of '+snapshot.rows.length+' companies'+(openMarket?' · Taiwan market data and EDGAR filings':market?' · USD market caps':' · SEC company facts');
 $('paging').textContent=visible.length?(start+1)+'–'+Math.min(start+size,visible.length)+' of '+visible.length:'0 results';
 $('prev').disabled=page===0;$('next').disabled=start+size>=visible.length;
}
function detail(r) {
 const st=r.statement,m=best(r),cycle=r.cycle||{};
 const capexDetail=v=>{
   if(v.tag!=='derived:CashCapitalInvestment'&&![st?.facts?.capex_reported_total,st?.facts?.capex_mixed_outflow,st?.facts?.capex_financing_payment,st?.facts?.capex_net_of_disposals,st?.facts?.capex_disposal_proceeds].includes(v)) return '';
   const components=v.components||[v];
   return '<details><summary>Filed cash investment lines</summary><ul>'+components.map(part=>{
     const source=part.table_url||part.source;
     return '<li>'+esc(part.locator)+' · '+esc(part.unit)+' '+reportedAmount.format(part.value)+' · <a target="_blank" rel="noopener noreferrer" href="'+safeUrl(source)+'">'+(part.table_url?(part.table_kind==='bmo_cash_flow_exhibit'?'SEC-filed financial statements':part.source===part.table_url?'SEC rendered statement':'SEC table via Canli Capital'):source.endsWith('.pdf')?'Filed PDF':'SEC Company Facts')+'</a></li>';
   }).join('')+'</ul></details>';
 };
 const componentDetail=v=>{
   if(!v.components?.[0]?.line) return '';
   const titles={
     'derived:FiledDepreciationAndAmortization':'Depreciation and amortization evidence',
     'disclosed:ReconciledAnnualNote':'Filed note components',
     'disclosed:ReconciledAnnualNoteLine':'Filed note line',
     'disclosed:ReconciledBusinessScopes':'Filed business-scope components',
     'disclosed:AnnualEarningsExhibit':'Annual filing and exhibit reconciliation',
   };
   const title=titles[v.tag]||'Filed income statement lines';
   const anchor=v.tag==='disclosed:ReconciledAnnualNote'&&v.rounding_increment?
     '<p class="minor">Reconciliation anchor · '+esc(v.unit)+' '+reportedAmount.format(v.anchor_value)+'</p>':'';
   return '<details><summary>'+title+'</summary>'+anchor+'<ul>'+v.components.map(part=>{
     const source=part.table_url||part.source||v.table_url;
     return '<li>'+esc(part.line.replace('::',' · '))+' · '+esc(v.unit)+' '+reportedAmount.format(part.sign*part.value)+
       ' · <a target="_blank" rel="noopener noreferrer" href="'+safeUrl(source)+'">Source</a></li>';
   }).join('')+'</ul></details>';
 };
 const factRows=period=>period?Object.entries(period.facts).map(([k,v])=>'<tr><td>'+esc(v.tag==='derived:FiledOperatingProfit'?'Derived operating profit':k==='da'&&period.facts.da_including_content?'D&A excluding content amortization':field(k))+'</td><td>'+(v.rounding_increment?'≈ ':'')+esc(v.unit||period.currency)+' '+reportedAmount.format(v.value)+'</td><td><a target="_blank" rel="noopener noreferrer" href="'+safeUrl(v.url)+'">'+esc(v.form||'Filing')+' · '+esc(v.filed)+'</a><br><span class="minor">'+esc(v.locator||v.tag)+'</span>'+capexDetail(v)+componentDetail(v)+(period.route==='rendered_10q'?'<br><a target="_blank" rel="noopener noreferrer" href="'+safeUrl(v.table_url)+'">SEC table via Canli Capital</a>':period.route==='sec_workbook'?'<br><a target="_blank" rel="noopener noreferrer" href="'+safeUrl(v.source)+'">Open10K workbook from SEC data</a>':['issuer_20f','regulator_20f'].includes(period.route)?'<br><a target="_blank" rel="noopener noreferrer" href="'+safeUrl(v.source)+'">Downloaded 20-F PDF</a>':(['issuer_inline','issuer_instance','issuer_10q'].includes(period.route)||v.tag?.startsWith('filing_claims:'))?'<br><a target="_blank" rel="noopener noreferrer" href="'+safeUrl(v.source)+'">Issuer filing copy</a>':'')+'</td></tr>').join(''):'';
 const factTable=body=>'<div class="tablewrap"><table><thead><tr><th scope="col">Metric</th><th scope="col">Amount</th><th scope="col">Filing and concept</th></tr></thead><tbody>'+body+'</tbody></table></div>';
 const interim=[['Standalone quarter',r.edgar?.quarter],['Fiscal year to date',r.edgar?.ytd]].filter(([,x])=>x).map(([title,p])=>'<details><summary>'+title+' · '+esc(p.start)+' to '+esc(p.end)+'</summary>'+factTable(factRows(p))+'</details>').join('');
 const q=r.market;
 const marketDetail=q?'<h3>Taiwan Stock Exchange</h3><p>'+esc(q.code)+' · NT$'+n2.format(q.close)+' close on '+esc(q.date)+'. Estimated common equity cap NT$'+money.format(q.estimated_cap_twd)+' uses '+n2.format(q.issued_shares)+' issued shares from '+esc(q.shares_date)+'.</p><p><a href="https://data.gov.tw/en/datasets/11549">Closing prices</a> · <a href="https://data.gov.tw/en/datasets/18419">Issuer registry</a> · <a href="https://data.gov.tw/dataset/11764">Exchange multiples</a></p>':'';
 const audit=r.edgar?.latest_annual?'<p>Latest annual filing in SEC submissions: <a href="'+safeUrl(r.edgar.latest_annual.url)+'" target="_blank" rel="noopener noreferrer">'+esc(r.edgar.latest_annual.end)+'</a>.</p>':'';
 const operatingGap=st?.operating_profit_gap?'<p>Operating profit pending · '+esc(st.operating_profit_gap)+'</p>':'';
 const depreciationGap=st?.depreciation_gap?'<p>Depreciation and amortization pending · '+esc(st.depreciation_gap)+'</p>':'';
 const investmentGap=st?.capital_investment_gap?'<p>Continuing cash investment pending · '+esc(st.capital_investment_gap)+'</p>':'';
 const succession=r.edgar?.succession;
 const lineage=succession?'<p><a href="'+safeUrl(succession.url)+'" target="_blank" rel="noopener noreferrer">Registrant succession effective '+esc(succession.effective)+'</a>. Earlier consolidated history retains the predecessor’s filing links.</p>':'';
 const amendmentReviews=(r.edgar?.amendment_reviews||[]).map(x=>'<li><a href="'+safeUrl(x.url)+'" target="_blank" rel="noopener noreferrer">'+esc(x.accession)+'</a> · '+esc(x.scope)+'</li>').join('');
 const amendments=amendmentReviews?'<p>The reviewed amendments leave the consolidated statement figures in the original filing intact.</p><ul>'+amendmentReviews+'</ul>':'';
 const percentInputs=new Set(['re','g','roe','wacc','payout','terminal_roic','terminal_roe','tax','capex_sales','da_sales','nwc_sales_proxy','growth_start','ebit_margin','target_margin','fcfe_sales','market_implied_dividend_growth','market_implied_terminal_ebit_margin','market_implied_roe']);
 const dl=obj=>'<dl class="fields">'+Object.entries(obj).map(([k,v])=>'<dt>'+esc(field(k))+'</dt><dd>'+esc(Array.isArray(v)?v.map(x=>typeof x==='number'?n2.format(x):x).join(', '):typeof v==='number'?(percentInputs.has(k)?pct(v):n2.format(v)):v)+'</dd>').join('')+'</dl>';
 const sources=factRows(st);
 const balance=r.balance_check;
 const reconciliation=balance&&(balance.temporary_equity_fields.length||!balance.reconciled||st.facts.hybrid_equity)?'<p>Balance sheet residual after disclosed temporary equity · '+esc(st.currency)+' '+reportedAmount.format(balance.unexplained_residual)+(balance.unexplained_equity_attribution!==undefined?' · Equity attribution residual '+reportedAmount.format(balance.unexplained_equity_attribution):'')+'</p>':'';
 const history=r.history||[], basis=st?.sales_basis??null;
 const comparable=history.slice(history.findLastIndex(h=>(h.sales_basis??null)!==basis)+1);
 const margins=comparable.flatMap(h=>h.facts.sales?.value>0&&Number.isFinite(h.facts.ebit?.value)?[[h.end.slice(0,4),h.facts.ebit.value/h.facts.sales.value]]:[]);
 const max=Math.max(.1,...margins.map(x=>Math.abs(x[1])));
 const chart=margins.length>=2?'<h3>Operating margin</h3><div class="spark" aria-label="Fiscal-year operating margins">'+margins.map(([y,v])=>'<div class="'+(v<0?'negative':'')+'"><span>'+pct(v)+'</span><b style="height:'+Math.max(2,Math.abs(v)*70/max)+'px"></b><span>'+esc(y)+'</span></div>').join('')+'</div>':'';
 const decisions=r.models?'<h3>Valuation decisions</h3>'+r.models.decisions.map(x=>'<details><summary><strong>'+esc(x.label)+'</strong> · '+(x.status==='estimated'?usd(x.equity_usd)+' ('+pct(x.gap)+')':esc(x.status.replaceAll('_',' ')))+'</summary><p>'+esc(x.reason)+'</p>'+(x.status==='estimated'?'<p>Range: '+usd(x.low_usd)+' to '+usd(x.high_usd)+'</p>'+dl(x.inputs)+(x.cycle_cases_usd?'<p>Cycle scenarios</p>'+dl(x.cycle_cases_usd):''):'')+'</details>').join(''):'';
 const ratios=Object.entries(r.ratios||{}).map(([k,v])=>'<dt>'+esc(k)+'</dt><dd>'+n2.format(v.multiple)+'×</dd>').join('');
 $('detail-title').textContent=r.name+' · '+r.symbol;
 $('content').innerHTML='<p class="lede">'+esc(label(r.kind))+' · '+esc(r.peer_group)+' · '+esc(r.classification)+'</p>'+
   marketDetail+(m?'<div class="notice">Lead model: '+esc(m.label)+' · '+usd(m.equity_usd)+' · '+pct(m.gap)+' vs. market cap</div>':'')+
   (ratios?'<h3>Observed multiples</h3><dl class="fields">'+ratios+'</dl>':'')+chart+
   (cycle.mid_margin!==undefined?'<p>Cycle: '+esc(cycle.phase)+' · current '+pct(cycle.actual_margin)+' vs. historical median '+pct(cycle.mid_margin)+' · '+esc(cycle.window.join(' to '))+'</p>':'')+
   decisions+'<h3>Annual filing evidence</h3>'+audit+lineage+amendments+operatingGap+depreciationGap+investmentGap+reconciliation+(sources?'<p>Fiscal year ended '+esc(st.end)+' · '+esc(r.accounting)+' · '+esc(r.source)+'</p>'+factTable(sources):'<p>No normalized annual statement.</p>')+
   (interim?'<h3>Latest SEC interim filing</h3>'+interim:'')+
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
fetch('snapshot.json',{cache:'no-cache'}).then(r=>{if(!r.ok)throw Error('No bundled snapshot');return r.json();}).then(setData).catch(()=>{
 if(!snapshot)$('scope').textContent='The hosted data could not load. Reload this page, or open a local snapshot.';
});
