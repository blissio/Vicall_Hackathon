'use strict';
(() => {
  let research = {job:{status:'idle'}, candidates:[], settings:{}, sources:{}, providers:[]};
  let initialized = false, page = 1, lastProgress = '', timer;
  const businessLabels = {unknown:'Operating status unknown',operating:'Reported operating',temporarily_closed:'Reported temporarily closed',permanently_closed:'Reported permanently closed'};
  const websiteLabels = {no_independent_url:'Independent website unknown',not_checked:'Website listed · not checked',reachable:'HTML reachable',unreachable:'Connection failed · recheck',http_error:'HTTP error · recheck',restricted:'Access restricted',unknown:'Website check inconclusive',non_html:'Responded · non-HTML'};
  const locationLabels = {mapped_location:'Mapped location',home_based:'Home-based',service_area:'Service-area business',storefront:'Storefront reported',online_only:'Online only',unknown:'Location unconfirmed'};

  function businessCell(row) {
    const s=row.research_status || {};
    return `<div class="business-state state-${esc(s.business || 'unknown')}">${esc(businessLabels[s.business] || businessLabels.unknown)}</div>${row._id.startsWith('osm:')?'':`<div class="source-tag">${esc(locationLabels[s.location_type] || 'External listing')}</div>`}`;
  }
  function websiteCell(row) {
    const s=row.research_status || {};
    return `<span>${esc(websiteLabels[s.website] || 'Website status unknown')}<small class="website-check-date">${s.website_checked_at?esc(date(s.website_checked_at)):'No independent check'}</small><small class="website-identity">${s.identity==='researcher_confirmed'?'Identity reviewed':'Identity unverified'}</small></span>`;
  }
  function contactCell(row) {
    const channels=[['Phone',row.phones],['Email',row.emails],['Social',row.social_urls],['Contact page',row.contact_pages]].filter(([,v])=>v?.length);
    return `<div class="contact-pills">${channels.map(([label,v])=>`<span class="contact-pill">${label} ${v.length}</span>`).join('') || '<span class="muted-cell">No channels found</span>'}</div><small class="contact-verification">${row.research_status?.contact_disagreements?.length?'Sources differ · verify branch':channels.length?'Listed / observed · unverified':'Coverage incomplete'}</small>`;
  }
  function evidence(row) {
    const contacts=row.contact_evidence || [];
    $('#detail-contact-evidence').innerHTML=`<details class="research-details"><summary>Sources for ${contacts.length} contact references</summary>${contacts.map(c=>`<article class="contact-evidence"><strong>${esc(c.kind.replaceAll('_',' '))}</strong><div>${['website','social','contact_page','contact_form'].includes(c.kind)?externalLink(c.value,c.value):esc(c.value)}</div><p>${esc(c.method)} · ${esc(date(c.observed_at))}</p><p>${externalLink(c.source_url,'Source page ↗')} · ${c.verification==='observed_not_verified'?'Observed on page':'Listed in source'} · not delivery-tested</p></article>`).join('') || '<p class="small-muted">No contact references recorded yet. Research the website or add a sourced public listing.</p>'}</details>${row.enrichment?`<p class="small-muted">${esc(row.enrichment.message || 'Research inconclusive')} Checked ${esc(date(row.enrichment.checked_at))}.</p><details class="research-details"><summary>Pages sampled (${row.enrichment.pages.length})</summary>${row.enrichment.pages.map(p=>`<p class="small-muted">${externalLink(p.url,p.url)} · ${esc(p.outcome)}${p.http_status?' · HTTP '+p.http_status:''}${p.message?' · '+esc(p.message):''}</p>`).join('')}</details>`:''}`;
  }
  function open(row, preserve=false) {
    const websites=[...new Set([...(row.websites || []), row.audit?.requested_url].filter(Boolean))];
    $('#detail-contacts').innerHTML=[['Website',websites.length?websites.map(url=>externalLink(url,url)).join(''):'Independent website unknown'],['Phone',row.phones?.length?row.phones.map(esc).join('<br>'):'No public number found'],['Email',row.emails?.length?row.emails.map(esc).join('<br>'):'No public email found'],['Social',row.social_urls?.length?row.social_urls.map(url=>externalLink(url,url)).join(''):'No social link observed'],['Contact page / form',row.contact_pages?.length?row.contact_pages.map(url=>externalLink(url,url)).join(''):'No contact page / form observed'],['Hours',esc(row.opening_hours || 'Not listed')],['Brand / operator',[row.brand,row.operator].filter(Boolean).map(esc).join(' / ') || 'Not listed']].map(([label,value])=>`<div class="detail-contact"><span>${label}</span><div>${value}</div></div>`).join('');
    if(preserve&&state.reviewDirty){evidence(row);return;}
    const saved=preserve&&state.reviewDirty?Object.fromEntries(['business-state','business-evidence','website-identity','identity-url','identity-evidence'].map(id=>[id,$('#detail-'+id)?.value])):null;
    const s=row.research_status || {}, w=row.workflow;
    $('#detail-business-status').innerHTML=`<h3>What we know right now</h3><div class="status-overview"><article><span>Business</span><strong class="state-${esc(s.business)}">${esc(businessLabels[s.business] || businessLabels.unknown)}</strong><small>${s.business_checked_at?'Reviewed '+esc(date(s.business_checked_at)):'A map, license, or working site does not prove operation'}</small></article><article><span>Website</span><strong>${esc(websiteLabels[s.website] || 'Unknown')}</strong><small>${s.website_checked_at?'Checked '+esc(date(s.website_checked_at)):'Not independently checked'} · ${s.identity==='researcher_confirmed'?'Identity reviewed':'Identity unverified'}</small></article><article><span>Contact</span><strong>${s.contact_disagreements?.length?'Contact differences to review':s.contact==='no_channels_found'?'No public channels found':s.contact==='social_only'?'Social channel only':'Public channels available'}</strong><small>${s.contact_disagreements?.length?'Different '+esc(s.contact_disagreements.join(' / '))+' values across sources; verify the branch.':'Listed / observed; ownership and delivery unverified'}</small></article><article><span>Location</span><strong>${esc(locationLabels[s.location_type] || 'Unknown')}</strong><small>${esc(row.service_area || row.neighborhood || 'Service area unconfirmed')}</small></article></div><p class="small-muted">${s.website_check_source?esc(s.website_check_source)+'. ':''}Source: ${esc(s.source)}. Research stage is your prospect decision, separate from operating status.</p><details class="research-details"><summary>Review operating status and website identity</summary><label class="field-label" for="detail-business-state">Business status</label><select id="detail-business-state"><option value="unknown">Operating status unknown</option><option value="operating">Reported operating</option><option value="temporarily_closed">Reported temporarily closed</option><option value="permanently_closed">Reported permanently closed</option></select><label class="field-label" for="detail-business-evidence">Business status evidence</label><textarea id="detail-business-evidence" maxlength="3000" placeholder="Source URL, observation, and date; a website error alone is not closure evidence."></textarea><label class="field-label" for="detail-website-identity">Website identity</label><select id="detail-website-identity"><option value="unverified">Unverified</option><option value="confirmed">Researcher confirmed</option></select><label class="field-label" for="detail-identity-url">Website URL matched to this business</label><input id="detail-identity-url" type="url" placeholder="https://…"><label class="field-label" for="detail-identity-evidence">Identity evidence</label><textarea id="detail-identity-evidence" maxlength="3000" placeholder="Explain the business-name, public-contact, or address match."></textarea><button id="save-business-review" class="button secondary">Save status review</button><p id="business-review-message" class="small-muted">${state.reviewDirty?'Unsaved status review':'A confirmation applies only to the reviewed URL.'}</p></details>`;
    $('#detail-business-state').value=w.business_status || 'unknown';
    $('#detail-business-evidence').value=w.business_evidence || '';
    $('#detail-website-identity').value=w.website_identity || 'unverified';
    $('#detail-identity-url').value=w.identity_url || row.audit?.requested_url || row.enrichment?.requested_url || row.websites?.[0] || '';
    $('#detail-identity-evidence').value=w.identity_evidence || '';
    if(saved) for(const [id,value] of Object.entries(saved)) $('#detail-'+id).value=value || '';
    for(const id of ['business-state','business-evidence','website-identity','identity-url','identity-evidence']) $('#detail-'+id).addEventListener('input',()=>{state.reviewDirty=true;$('#business-review-message').textContent='Unsaved status review';});
    evidence(row);
    $('#detail-enrich').disabled=research.job.status==='running';
  }
  function selectedSources() {return $$('#research-providers input:checked').map(el=>el.value);}
  function render() {
    const inbox=research.candidates.filter(c=>c.review_status==='new');
    $('#nav-discovery').textContent=count(inbox.length);
    $('#research-stats').innerHTML=[['Awaiting review',inbox.length,'Public-source leads, not verified businesses'],['Websites researched',research.enriched || 0,'Up to four pages per business'],['Operating status known',state.rows.filter(r=>r.research_status?.business!=='unknown').length,'Researcher-reviewed evidence'],['Service-area / home leads',state.rows.filter(r=>['home_based','service_area'].includes(r.research_status?.location_type)).length,'No street address required']].map(([label,value,foot])=>`<article class="stat-card"><div class="stat-label">${label}</div><div class="stat-value">${count(value)}</div><div class="stat-foot">${foot}</div></article>`).join('');
    const job=research.job, running=job.status==='running';
    $('#research-progress').innerHTML=`<div class="job-head"><span class="job-dot ${esc(job.status)}"></span><strong>${esc(job.message || 'Ready')}</strong></div><p>${count(job.completed)} of ${count(job.total)} tasks · ${count(job.skipped)} skipped (no independent URL or recent result)</p>`;
    $('#research-cancel').hidden=!running;
    for(const id of ['research-matching','research-sources','enrich-selected','detail-enrich']) $('#'+id).disabled=running;
    $('#automation-summary').textContent=research.settings.enabled?`Enabled while app is open · up to ${research.settings.batch_size} websites/run · last automatic start: ${date(research.settings.last_started_at)}`:'Automation disabled. Manual research remains available.';
    $('#research-source-status').innerHTML=Object.values(research.sources).map(s=>`<p class="small-muted">${externalLink(s.url,research.providers.find(p=>p.key===s.source)?.name || 'Public directory')} · ${count(s.returned)} of ${count(s.source_total)} source records sampled · ${esc(date(s.observed_at))}${s.limited?' · capped sample; coverage incomplete':''}</p>`).join('')+(job.errors || []).map(e=>`<p class="research-error">${esc(e.target)}: ${esc(e.message)}</p>`).join('');
    const q=$('#discovery-search').value.trim().toLowerCase(), status=$('#discovery-state').value;
    const rows=research.candidates.filter(c=>(!status || c.review_status===status)&&(!q || [c.name,c.category,c.service_area,c.source.provider].join(' ').toLowerCase().includes(q))).sort((a,b)=>a.name.localeCompare(b.name));
    page=Math.min(page,Math.max(1,Math.ceil(rows.length/15)));
    $('#discovery-count').textContent=count(rows.length);
    $('#discovery-results').innerHTML=rows.slice((page-1)*15,page*15).map(c=>`<article class="discovery-result"><div><h3>${esc(c.name)}</h3><p>${esc(c.category)} · ${esc(c.service_area)}</p><p>${externalLink(c.source.url,c.source.provider+' ↗')} · collected ${esc(date(c.source.collected_at))}</p>${c.description?`<p>${esc(c.description)}</p>`:''}<div class="contact-pills">${c.websites.length?'<span class="contact-pill">Website listed</span>':''}${c.phones.length?'<span class="contact-pill">Phone listed</span>':''}${c.emails.length?'<span class="contact-pill">Email listed</span>':''}${c.social_urls?.length?'<span class="contact-pill">Social listed</span>':''}</div><p class="small-muted">Operation, identity, and service area unconfirmed.${c.license_evidence?.state?' License record: '+esc(c.license_evidence.state)+'; expiry '+esc(c.license_evidence.expires || 'unlisted')+'. A license status is not an operating-status check.':''}</p>${c.possible_matches?.length?`<div class="duplicate-evidence">Possible name matches: ${c.possible_matches.map(m=>`<button class="text-button" data-open="${esc(m.id)}">${esc(m.name)}</button>`).join('')} · verify branch / identity before adding.</div>`:''}</div><div class="discovery-actions">${c.review_status==='new'?`<button class="button secondary" data-candidate="${esc(c.id)}" data-action="add">${c.possible_matches?.length?'Add separate business':'Add to directory'}</button><button class="text-button" data-candidate="${esc(c.id)}" data-action="dismiss">Dismiss lead</button>`:c.review_status==='added'?`<button class="text-button" data-open="${esc(c.added_id)}">Open added business</button>`:`<button class="text-button" data-candidate="${esc(c.id)}" data-action="restore">Restore to inbox</button>`}</div></article>`).join('') || '<div class="empty-state"><h3>No leads match this view</h3><p>Update a public directory or save a sourced business listing below.</p></div>';
    $('#discovery-page-summary').textContent=rows.length?`${count((page-1)*15+1)}–${count(Math.min(page*15,rows.length))} of ${count(rows.length)} leads`:'No leads';
    $('#discovery-page-number').textContent=`${page} / ${Math.max(1,Math.ceil(rows.length/15))}`;
    $('#discovery-previous').disabled=page<=1;$('#discovery-next').disabled=page*15>=rows.length;
  }
  async function refresh() {
    research=await (await api('/api/research')).json();
    if(!initialized){
      $('#automation-enabled').checked=research.settings.enabled;
      $('#automation-interval').value=String(research.settings.interval_hours);
      $('#automation-batch').value=String(research.settings.batch_size);
      $('#research-providers').innerHTML=research.providers.map(p=>`<label class="check-label"><input type="checkbox" value="${esc(p.key)}" ${research.settings.sources.includes(p.key)?'checked':''}>${esc(p.name)}</label>`).join('');
      initialized=true;
    }
    const key=`${research.job.started_at}:${research.job.completed}:${research.job.status}`;
    if(key!==lastProgress){lastProgress=key;await loadData();if(state.detail){const row=state.rows.find(r=>r._id===state.detail);if(row)open(row,true);}}
    render();
  }
  async function poll(){try{await refresh();}catch(e){if(state.view==='research')$('#research-progress').textContent=e.message;}finally{timer=setTimeout(poll,research.job.status==='running'?2500:15000);}}
  async function start(ids=[],sources=[],force=$('#research-force').checked){
    if(ids.length>25)return toast('Choose up to 25 businesses per research batch.',true);
    if(!ids.length&&!sources.length)return toast('Choose businesses with an independent website or a public directory source.');
    try{research.job=await (await api('/api/research',{ids,sources,force})).json();render();toast('Public-source research started');clearTimeout(timer);timer=setTimeout(poll,700);}catch(e){toast(e.message,true);}
  }
  $('#research-matching').addEventListener('click',()=>start(state.filtered.filter(r=>{
    const hasURL=r.research_status?.website!=='no_independent_url';
    const age=Date.now()-new Date(r.enrichment?.checked_at).getTime();
    return hasURL&&($('#research-force').checked||!r.enrichment||!Number.isFinite(age)||age<0||age>=86400000);
  }).map(r=>r._id).slice(0,10)));
  $('#research-sources').addEventListener('click',()=>start([],selectedSources()));
  $('#enrich-selected').addEventListener('click',()=>start([...state.selected]));
  $('#detail-enrich').addEventListener('click',()=>start([state.detail],[],true));
  $('#research-cancel').addEventListener('click',async()=>{try{research.job=await (await api('/api/research-cancel',{})).json();render();}catch(e){toast(e.message,true);}});
  $('#save-automation').addEventListener('click',async()=>{try{research.settings=await (await api('/api/research-settings',{enabled:$('#automation-enabled').checked,interval_hours:Number($('#automation-interval').value),batch_size:Number($('#automation-batch').value),sources:selectedSources()})).json();render();toast('Automation settings saved');}catch(e){toast(e.message,true);}});
  $('#discovery-search').addEventListener('input',()=>{page=1;render();});$('#discovery-state').addEventListener('change',()=>{page=1;render();});
  $('#discovery-previous').addEventListener('click',()=>{page--;render();});$('#discovery-next').addEventListener('click',()=>{page++;render();});
  $('#discovery-form').addEventListener('submit',async e=>{e.preventDefault();const form=e.target;try{await api('/api/discovery-add',Object.fromEntries(new FormData(form)));await refresh();form.reset();toast('Public business lead saved for review');}catch(err){toast(err.message,true);}});
  $('#discovery-csv').addEventListener('change',async e=>{const file=e.target.files[0];if(!file)return;if(file.size>500000)return toast('Choose a CSV under 500 KB.',true);try{const result=await (await api('/api/discovery-import',{csv:await file.text()})).json();$('#discovery-import-result').textContent=`${result.added} added · ${result.existing} already saved · ${result.errors.length} rejected. ${result.errors.slice(0,5).map(r=>'Row '+r.row+': '+r.message).join(' ')}`;await refresh();}catch(err){toast(err.message,true);}finally{e.target.value='';}});
  document.addEventListener('click',async e=>{
    const candidate=e.target.closest('[data-candidate]');
    if(candidate){candidate.disabled=true;try{await api('/api/discovery-review',{id:candidate.dataset.candidate,action:candidate.dataset.action});await loadData();await refresh();toast(candidate.dataset.action==='add'?'Added to directory as an unverified business':'Discovery review saved');}catch(err){toast(err.message,true);}finally{candidate.disabled=false;}}
    if(e.target.closest('#save-business-review')){
      const payload={business_status:$('#detail-business-state').value,business_evidence:$('#detail-business-evidence').value,website_identity:$('#detail-website-identity').value,identity_url:$('#detail-identity-url').value,identity_evidence:$('#detail-identity-evidence').value};
      try{await patchWorkflow(state.detail,payload);state.reviewDirty=false;await loadData();open(state.rows.find(r=>r._id===state.detail),true);toast('Business status and identity evidence saved');}catch(err){toast(err.message,true);}
    }
  });
  window.vicallResearch={render,open,businessCell,websiteCell,contactCell};
  renderTable();poll();
})();
