'use strict';
(() => {
  const collectionActions = $('#job-panel').previousElementSibling;
  collectionActions.insertAdjacentHTML('beforeend','<button id="collection-stop" class="button secondary" hidden>Stop collection</button><button id="collection-resume" class="button secondary" hidden>Resume unfinished collection</button>');
  const originalRenderJob=renderJob;
  renderJob=function(job){originalRenderJob(job);$('#collection-stop').hidden=job.status!=='running';$('#collection-resume').hidden=!['failed','cancelled','interrupted'].includes(job.status);$('#collection-stop').disabled=state.teamRole==='viewer'||state.teamRole==='researcher';$('#collection-resume').disabled=$('#collection-stop').disabled;};
  $('#collection-stop').onclick=async()=>{try{renderJob(await(await api('/api/collect-cancel',{})).json());toast('Stopping collection; your saved directory stays available');}catch(e){toast(e.message,true);}};
  $('#collection-resume').onclick=async()=>{try{renderJob(await(await api('/api/collect-resume',{})).json());toast('Resuming with saved source responses');}catch(e){toast(e.message,true);}};
  let currentBusiness=null;
  const statusLabel=status=>({not_run:'Not checked yet',running:'Checking',complete:'Completed',inconclusive:'No conclusion',interrupted:'Interrupted'}[status] || status);
  function reportHTML(report, kind) {
    let text=`<p><strong>${esc(statusLabel(report.status))}</strong> · ${esc(report.message || '')}</p>`;
    if(report.checked_at)text+=`<p class="small-muted">Observed ${esc(date(report.checked_at))} · ${esc(report.requested_url || '')}${report.strategy?' · '+esc(report.strategy):''}</p>`;
    if(report.status!=='complete')return text;
    if(kind==='links')text+=`<p>${report.links.length} of ${report.total_internal_links_found} links sampled · ${report.missing_count} returned 404/410</p>`+report.links.map(link=>`<p>${externalLink(link.url,link.url)} · ${esc(link.outcome)}${link.http_status?' · HTTP '+link.http_status:''}</p>`).join('');
    if(kind==='performance'){
      text+='<h4>Lighthouse lab scores</h4>'+Object.entries(report.categories).map(([key,value])=>`<p>${esc(key.replaceAll('-',' '))}: ${value==null?'Unavailable':value+'/100'}</p>`).join('');
      text+='<h4>Lab measurements</h4>'+report.lab_metrics.map(m=>`<p>${esc(m.title)}: ${esc(m.display_value || String(m.numeric_value??'Unavailable'))}</p>`).join('');
      text+=`<p class="small-muted">${Object.keys(report.field_data || {}).length?'Google also returned field samples; see the evidence download.':'No real-user field sample was returned. Use the separate real-user check when configured.'}</p>`;
      text+=externalLink(report.report_url,'Open Google report ↗')+'<details><summary>Findings</summary>'+report.findings.map(f=>`<p><strong>${esc(f.title || f.id)}</strong><br>${esc(f.description)}${f.display_value?'<br>'+esc(f.display_value):''}</p>`).join('')+'</details>';
    }
    if(kind==='field'){
      text+='<h4>Real-user 75th percentile</h4>'+Object.entries(report.field_metrics).filter(([,m])=>m.percentiles?.p75!=null).map(([key,m])=>`<p>${esc(key.replaceAll('_',' '))}: ${esc(String(m.percentiles.p75))}${['largest_contentful_paint','interaction_to_next_paint','first_contentful_paint','experimental_time_to_first_byte'].includes(key)?' ms':key==='cumulative_layout_shift'?' (unitless)':''}</p>`).join('');
      if(report.collection_period)text+=`<p class="small-muted">Aggregation period: ${esc(JSON.stringify(report.collection_period))}</p>`;
    }
    if(report.history?.length)text+=`<details><summary>${report.history.length} previous reports</summary>${report.history.map(h=>`<p>${esc(date(h.checked_at))} · ${esc(statusLabel(h.status))} · ${esc(h.strategy || '')}</p>`).join('')}</details>`;
    return text;
  }
  async function refresh(id, kind){const path=kind==='links'?'link':kind;const report=await(await api('/api/'+path+'-report?id='+encodeURIComponent(id))).json();if(currentBusiness!==id || state.detail!==id)return;$('#extra-'+kind+'-report').innerHTML=reportHTML(report,kind);}
  function open(id){
    currentBusiness=id;
    const panel=document.createElement('div');panel.id='extended-audit-controls';
    panel.innerHTML='<h3>Links &amp; performance</h3><p class="small-muted">Use the website URL entered above. Google checks send this public URL to Google; no research notes are sent.</p>'+[['links','Sample internal links','Check up to 10 links'],['performance','Google Lighthouse lab test','Run Lighthouse via Google'],['field','Real-user Core Web Vitals','Fetch real-user metrics']].map(([kind,title,label])=>`<details class="research-details"><summary>${title}</summary>${kind!=='links'?`<label class="field-label" for="extra-${kind}-strategy">Device</label><select id="extra-${kind}-strategy"><option value="mobile">Mobile</option><option value="desktop">Desktop</option></select>`:''}<div class="profile-actions"><button class="button secondary" data-extra-start="${kind}">${label}</button><button class="text-button" data-extra-refresh="${kind}">Refresh result</button><button class="text-button" data-extra-download="${kind}">Download evidence</button></div><div id="extra-${kind}-report"></div></details>`).join('');
    $('#detail-intelligence').appendChild(panel);
    panel.addEventListener('click',async e=>{
      const start=e.target.closest('[data-extra-start]'), reload=e.target.closest('[data-extra-refresh]'), download=e.target.closest('[data-extra-download]');
      try{
        if(start){const kind=start.dataset.extraStart,path=kind==='links'?'link':kind;start.disabled=true;await api('/api/'+path+'-audit',{id,url:$('#detail-audit-url').value,strategy:kind==='links'?'mobile':$('#extra-'+kind+'-strategy').value});await refresh(id,kind);}
        if(reload)await refresh(id,reload.dataset.extraRefresh);
        if(download){const kind=download.dataset.extraDownload,path=kind==='links'?'link':kind;const response=await api('/api/'+path+'-report?id='+encodeURIComponent(id)),url=URL.createObjectURL(await response.blob());const a=document.createElement('a');a.href=url;a.download=path+'-evidence.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
      }catch(error){toast(error.message,true);}finally{if(start)start.disabled=state.teamRole==='viewer';}
    });
    panel.querySelectorAll('[data-extra-start]').forEach(b=>b.disabled=state.teamRole==='viewer');
    for(const kind of ['links','performance','field'])refresh(id,kind).catch(e=>{if(state.detail===id)$('#extra-'+kind+'-report').textContent=e.message;});
  }
  window.vicallExtended={open};
})();
