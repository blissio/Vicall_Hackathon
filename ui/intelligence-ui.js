'use strict';
(() => {
  titles.intelligence = ['Research assistant', 'Find providers, prospects, and potential partners using retained evidence.', 'Research assistant'];
  let current = null, saved = [], history = [], requestSequence = 0, personEdit = null;
  const dirtyForms = {organization:false, person:false};
  const updateDirty = () => {state.intelligenceDirty=dirtyForms.organization || dirtyForms.person;};
  const originalSwitch = switchView;
  switchView = function(view) {
    originalSwitch(view);
    $('#intelligence-view').hidden = view !== 'intelligence';
    if (view === 'intelligence') {
      $('#stats').hidden = true; $('#collect-top').hidden = true;
      refresh().catch(e => toast(e.message, true));
    }
  };
  const originalOpen = openDetail;
  openDetail = function(id) {
    if (state.intelligenceDirty && !confirm('Discard unsaved organization or contact research?')) return;
    originalOpen(id);
    if (state.detail === id && !state.dirty && !state.reviewDirty) { dirtyForms.organization=false; dirtyForms.person=false; personEdit=null; updateDirty(); renderProfile(id).catch(e => { $('#detail-intelligence').textContent = e.message; }); }
  };
  const originalClose = closeDetail;
  closeDetail = function(force=false) {
    if (!force && state.intelligenceDirty && !confirm('Discard unsaved organization or contact research?')) return;
    originalClose(force);
    if ($('#detail-drawer').hidden) {dirtyForms.organization=false;dirtyForms.person=false;updateDirty();}
  };
  $('#detail-intelligence').addEventListener('input', e => {if(e.target.id.startsWith('org-'))dirtyForms.organization=true;if(e.target.id.startsWith('person-'))dirtyForms.person=true;updateDirty();});
  window.addEventListener('beforeunload', e => {if(state.intelligenceDirty){e.preventDefault();e.returnValue='';}});
  const observationDate = () => new Date().toISOString().slice(0, 10);
  function query() {
    return {question: $('#intelligence-question').value, intent: $('#intelligence-intent').value,
      segment: $('#intelligence-segment').value, organization_type: $('#intelligence-type').value,
      desired_services:$('#intelligence-desired').value, partner_services:$('#intelligence-partner').value,
      ...($('#intelligence-contact').checked ? {require_contact:true} : {}), ...($('#intelligence-person').checked ? {require_decision_maker:true} : {}),
      ...($('#intelligence-issue').checked ? {require_website_issue:true} : {}), limit: Number($('#intelligence-limit').value)};
  }
  function fill(q) {
    $('#intelligence-question').value = q.question || ''; $('#intelligence-intent').value = q.intent || 'prospects';
    $('#intelligence-segment').value = q.segment || ''; $('#intelligence-type').value = q.organization_type || '';
    $('#intelligence-limit').value = q.limit || 10;
    $('#intelligence-contact').checked = !!q.require_contact; $('#intelligence-person').checked = !!q.require_decision_maker;
    $('#intelligence-issue').checked = !!q.require_website_issue;
    $('#intelligence-desired').value=q.desired_services || '';$('#intelligence-partner').value=q.partner_services || '';
  }
  async function refresh() {
    const info = await (await api('/api/intelligence')).json();
    saved = info.saved_searches; history = info.history;
    const weightLabels={relevance:'Service/category relevance',observed_need:'Observed website need',public_contact:'Public contact channel',reviewed_role:'Reviewed public role',recent_evidence:'Recent source evidence',reviewed_identity:'Reviewed website identity',partner_fit:'Complementary services'};
    $('#matching-weights').innerHTML=Object.entries(info.matching_weights).map(([key,value])=>`<label>${esc(weightLabels[key] || key)}<input type="number" min="0" max="100" step="1" data-weight="${esc(key)}" value="${value}"></label>`).join('');
    $('#matching-save').disabled=!!info.team_role && info.team_role!=='admin';
    for(const id of ['intelligence-save','intelligence-delete-search','intelligence-resume','intelligence-resume-audits']) $('#'+id).disabled=info.team_role==='viewer';
    for(const id of ['intelligence-backup','intelligence-targets']) $('#'+id).disabled=!!info.team_role && info.team_role!=='admin';
    $('#intelligence-status').textContent = `${info.demo ? 'Fictional offline demo · ' : ''}SQLite research memory · ${info.ai_available ? 'AI configured: '+info.model : 'Evidence search ready; AI requires server configuration'} · Automation ${info.automation_enabled ? 'enabled' : 'disabled'}`;
    $('#intelligence-ai').disabled = !info.ai_available;
    $('#intelligence-plan').disabled = !info.ai_available || info.ai_mode!=='cloud';
    if(info.ai_mode!=='cloud')$('#intelligence-plan').checked=false;
    $('#intelligence-ai').parentElement.lastChild.textContent=info.ai_mode==='local_test'?'Use AI to explain the first result (local test)':'Use AI to interpret evidence';
    $('#intelligence-ai').dataset.mode=info.ai_mode;
    if(!info.ai_available)$('#intelligence-plan').checked=false;
    if (!info.ai_available) $('#intelligence-ai').checked = false;
    const previous = $('#intelligence-saved').value;
    $('#intelligence-saved').innerHTML = '<option value="">Choose a saved search</option>' + saved.map(s => `<option value="${esc(s.id)}">${esc(s.name)}</option>`).join('');
    $('#intelligence-saved').value = previous;
    $('#intelligence-history').innerHTML = history.map((a,i) => `<p><button class="text-button" data-answer="${i}">${esc(a.query.question || a.query.intent)} · ${esc(date(a.created_at))}</button></p>`).join('') || '<p>No research answers saved yet.</p>';
  }
  function evidenceHTML(e) {
    return `<article class="contact-evidence"><strong>${esc(e.kind.replaceAll('_',' '))}${e.stale ? ' · stale / date unknown' : ''}</strong><p class="evidence-excerpt">${esc(e.text)}</p><p>${externalLink(e.source_url, 'Source ↗')} · ${esc(date(e.observed_at))} · ${esc(e.method || '')}</p></article>`;
  }
  function render(answer) {
    current = answer;
    fill(answer.query);
    $('#intelligence-export').disabled = !answer.results.length;
    $('#intelligence-json').disabled = false;
    $('#intelligence-message').textContent = `${answer.total} matches · ${answer.metrics.elapsed_ms} ms retrieval · ${answer.metrics.external_page_requests} external page requests${answer.metrics.input_tokens != null ? ' · '+answer.metrics.input_tokens+' input tokens' : ''}`;
    const interpretations = new Map((answer.ai?.recommendations || []).map(r => [r.business_id,r]));
    $('#intelligence-results').innerHTML = `<p class="small-muted">${esc(answer.ranking_note)}</p>${answer.query_plan_error ? `<p class="alert error">${esc(answer.query_plan_error)}</p>` : ''}${answer.query_plan ? '<p class="directory-note">AI interpreted the question. Review the applied filters above.</p>' : ''}${answer.ai_error ? `<p class="alert error">${esc(answer.ai_error)}</p>` : ''}${answer.ai ? `<p class="directory-note">${esc(answer.ai.validation)}</p>` : ''}` + answer.results.map(r => {
      const ai = interpretations.get(r.id);
      return `<article class="data-card intelligence-result"><div class="panel-heading"><div><button class="business-name" data-research-open="${esc(r.id)}">${esc(r.name)}</button><p>${esc(r.category)} · ${esc(r.organization_type.replaceAll('_',' '))}</p></div><strong>${r.score}/100 heuristic</strong></div><p>${esc(r.services || 'Services need source review')}</p><p class="small-muted">${esc(r.reasons.join(' · '))}</p>${ai ? `<div class="ai-interpretation"><strong>AI interpretation · review required</strong><p>${esc(ai.interpretation)}</p><p>Cited evidence: ${ai.evidence_ids.map(esc).join(', ')}</p>${answer.mode==='local_ai_experiment'?ai.citations.map(c=>`<p class="local-source-quote">${esc(c.text)}<br>${externalLink(c.source_url,'Read source ↗')}</p>`).join(''):''}</div>` : ''}<p class="small-muted">${esc(r.unknowns.join(' · '))}</p>${r.contacts.map(p => `<p>${esc(p.name)} · ${esc(p.role)} · ${externalLink(p.source_url,'Public role source ↗')}</p>`).join('')}<details><summary>${r.evidence.length} evidence records</summary>${r.evidence.map(evidenceHTML).join('')}</details><div class="heading-actions"><button class="button secondary" data-research-save="${esc(r.id)}">${r.shortlisted ? 'Saved to shortlist' : 'Save to shortlist'}</button><button class="button secondary" data-research-open="${esc(r.id)}">Review profile</button></div></article>`;
    }).join('') + (!answer.results.length ? '<div class="empty-state"><h3>No matching evidence</h3><p>Broaden the sector or remove requirements. Import and review organizations in Discovery &amp; research.</p></div>' : '') + (answer.ai?.unknowns.length ? `<p>${answer.ai.unknowns.map(esc).join(' · ')}</p>` : '');
  }
  $('#intelligence-form').addEventListener('submit', async e => {
    e.preventDefault(); $('#intelligence-submit').disabled = true; $('#intelligence-message').textContent = $('#intelligence-ai').checked && $('#intelligence-ai').dataset.mode==='local_test'?'Loading the small local model and explaining one result. This may take up to 3 minutes on this laptop; it unloads afterward…':'Retrieving saved evidence…';
    try { render(await (await api('/api/ask', {...query(), use_ai: $('#intelligence-ai').checked, use_ai_plan:$('#intelligence-plan').checked})).json()); await refresh(); }
    catch (error) { $('#intelligence-message').textContent = error.message; }
    finally { $('#intelligence-submit').disabled = false; }
  });
  $('#intelligence-save').addEventListener('click', async () => {
    const name = prompt('Name this saved search'); if (!name) return;
    try { await api('/api/saved-search', {name, query: query()}); await refresh(); toast('Search saved'); } catch(e) {toast(e.message,true);}
  });
  $('#matching-save').addEventListener('click',async()=>{try {const weights=Object.fromEntries($$('[data-weight]').map(e=>[e.dataset.weight,Number(e.value)]));await api('/api/matching-settings',{weights});$('#matching-message').textContent='Ranking weights saved. Run a search to use them.';}catch(e){$('#matching-message').textContent=e.message;}});
  $('#intelligence-saved').addEventListener('change', () => { const s = saved.find(s => s.id === $('#intelligence-saved').value); if(s) fill(s.query); });
  $('#intelligence-delete-search').addEventListener('click', async () => { const id = $('#intelligence-saved').value; if(!id) return; try {await api('/api/saved-search-delete',{id}); await refresh();} catch(e) {toast(e.message,true);} });
  $('#intelligence-results').addEventListener('click', async e => {
    const open = e.target.closest('[data-research-open]'); if(open) openDetail(open.dataset.researchOpen);
    const save = e.target.closest('[data-research-save]'); if(save) try {await patchWorkflow(save.dataset.researchSave,{shortlisted:true}); save.textContent='Saved to shortlist'; const r=current.results.find(r=>r.id===save.dataset.researchSave); if(r)r.shortlisted=true;} catch(e) {toast(e.message,true);}
  });
  $('#intelligence-history').addEventListener('click', e => {const b=e.target.closest('[data-answer]');if(b){const a=history[Number(b.dataset.answer)];fill(a.query);render(a);}});
  async function download(path, payload, filename) {
    const response=await api(path,payload), url=URL.createObjectURL(await response.blob());
    const a=document.createElement('a');a.href=url;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  $('#intelligence-export').addEventListener('click', async () => {try {await download('/api/export',{ids:current.results.map(r=>r.id)},'pittsburgh-research.csv');} catch(e){toast(e.message,true);}});
  $('#intelligence-json').addEventListener('click', () => {const url=URL.createObjectURL(new Blob([JSON.stringify(current,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='research-evidence.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
  $('#intelligence-backup').addEventListener('click', async () => {try {const r=await (await api('/api/backup',{})).json();toast('Backup saved: '+r.path);}catch(e){toast(e.message,true);}});
  $('#intelligence-targets').addEventListener('click', async () => {try {const r=await (await api('/api/target-catalog',{})).json();toast(`${r.added} starter sources added. Review them in Discovery & research.`);window.vicallResearch?.render();}catch(e){toast(e.message,true);}});
  $('#intelligence-resume').addEventListener('click', async () => {try {await api('/api/research-resume',{});toast('Unfinished research resumed');}catch(e){toast(e.message,true);}});
  $('#intelligence-resume-audits').addEventListener('click', async () => {try {await api('/api/audit-resume',{});toast('Unfinished audits resumed');}catch(e){toast(e.message,true);}});
  function field(id,label,value='',type='text') {return `<label class="field-label" for="${id}">${esc(label)}</label><input id="${id}" type="${type}" value="${esc(value)}">`;}
  async function renderProfile(id) {
    const draft = {};
    for(const element of $$('#detail-intelligence input,#detail-intelligence select,#detail-intelligence textarea')) {
      if(element.id.startsWith('org-') && dirtyForms.organization || element.id.startsWith('person-') && dirtyForms.person) draft[element.id]=element.value;
    }
    const sequence=++requestSequence; $('#detail-intelligence').textContent='Loading organization research…';
    const detail=await (await api('/api/business?id='+encodeURIComponent(id))).json();
    if(state.detail!==id || sequence!==requestSequence)return;
    const suggestion=detail.business.organization_suggestion || {};
    const r=Object.keys(detail.review).length ? detail.review : {organization_type:suggestion.organization_type,services:suggestion.services,source_url:detail.business.source?.url,observed_at:suggestion.observed_at,excerpt:suggestion.source_excerpt,service_area:detail.business.service_area};
    $('#detail-intelligence').innerHTML=`<h3>Organization &amp; decision-maker research</h3><p class="small-muted">A sourced public role does not establish purchasing authority.</p><details><summary>Review organization and services</summary><label class="field-label" for="org-type">Organization type</label><select id="org-type"><option value="business">Business</option><option value="school_district">School district</option><option value="school">School</option><option value="nonprofit">Nonprofit</option><option value="public_body">Public body</option></select>${field('org-services','Services',r.services)}${field('org-area','Service area',r.service_area)}<label class="field-label" for="org-parent">Parent organization / district</label><select id="org-parent"><option value="">None / unknown</option>${state.rows.filter(row=>row._id!==id).map(row=>`<option value="${esc(row._id)}">${esc(row.name)}</option>`).join('')}</select>${field('org-source','Source URL',r.source_url,'url')}${field('org-date','Observed date',r.observed_at?.slice(0,10)||observationDate(),'date')}<label class="field-label" for="org-excerpt">Supporting source text</label><textarea id="org-excerpt" maxlength="4000">${esc(r.excerpt||'')}</textarea><button id="org-save" class="button secondary">Save organization review</button></details><div id="people-list">${detail.contacts.map(p=>`<article class="contact-evidence"><strong>${esc(p.name)} · ${esc(p.role)}</strong><p>${esc([p.email,p.phone].filter(Boolean).join(' · '))}</p><p>${externalLink(p.source_url,'Public source ↗')} · ${esc(date(p.observed_at))}</p><p>${esc(p.excerpt)}</p><button class="text-button" data-edit-person="${esc(p.id)}">Edit contact</button><button class="text-button" data-delete-person="${esc(p.id)}">Remove contact</button></article>`).join('')||'<p class="small-muted">No reviewed person/role yet.</p>'}</div><details><summary>Add a sourced public person and role</summary>${field('person-name','Name')}${field('person-role','Public role')}${field('person-email','Public business email','','email')}${field('person-phone','Public business phone')}${field('person-source','Source URL','','url')}${field('person-date','Observed date',observationDate(),'date')}<label class="field-label" for="person-excerpt">Supporting source text</label><textarea id="person-excerpt" maxlength="4000"></textarea><button id="person-save" class="button secondary">Save reviewed public role</button></details>${detail.suggested_contacts.length?`<details><summary>${detail.suggested_contacts.length} unreviewed public-role suggestions</summary>${detail.suggested_contacts.map((p,i)=>`<p>${esc(p.name)} · ${esc(p.role)} · ${externalLink(p.source_url,'Source ↗')} <button class="text-button" data-person-suggestion="${i}">Fill review form</button></p>`).join('')}</details>`:''}<details><summary>Rendered website audit</summary><p class="small-muted">Optional Playwright worker, with bounded public-resource fetching. Screenshots may omit third-party resources.</p><button id="rendered-start" class="button secondary">Run rendered audit</button><button id="rendered-refresh" class="button secondary">Refresh rendered result</button><div id="rendered-result"></div></details><p id="profile-research-message" role="status"></p>`;
    $('#org-type').value=r.organization_type||'business';$('#org-parent').value=r.parent_id||'';
    for(const [key,value] of Object.entries(draft)) if($('#'+key)) $('#'+key).value=value;
    const value=s=>$('#'+s).value;
    let organizationRevision=detail.review.revision || null;
    let editingPerson=personEdit?.business_id===id ? personEdit : null;
    if(editingPerson){$('#person-save').textContent='Save contact changes';$('#person-name').closest('details').open=true;}
    $('#org-save').onclick=async()=>{try {const saved=await(await api('/api/organization',{id,expected_revision:organizationRevision,organization_type:value('org-type'),services:value('org-services'),service_area:value('org-area'),parent_id:value('org-parent'),source_url:value('org-source'),observed_at:value('org-date'),excerpt:value('org-excerpt')})).json();organizationRevision=saved.revision;dirtyForms.organization=false;updateDirty();toast('Organization review saved');}catch(e){$('#profile-research-message').textContent=e.message;}};
    $('#person-save').onclick=async()=>{try {await api('/api/person',{...(editingPerson?{id:editingPerson.id}:{}),expected_revision:editingPerson?.revision || null,business_id:id,name:value('person-name'),role:value('person-role'),email:value('person-email'),phone:value('person-phone'),source_url:value('person-source'),observed_at:value('person-date'),excerpt:value('person-excerpt')});dirtyForms.person=false;personEdit=null;updateDirty();await renderProfile(id);toast('Public role saved');}catch(e){$('#profile-research-message').textContent=e.message;}};
    $('#people-list').onclick=async e=>{const edit=e.target.closest('[data-edit-person]');if(edit){const person=detail.contacts.find(p=>p.id===edit.dataset.editPerson);personEdit=person;editingPerson=person;for(const key of ['name','role','email','phone','source','date','excerpt'])$('#person-'+key).value=key==='source'?person.source_url:key==='date'?person.observed_at.slice(0,10):person[key]||'';$('#person-name').closest('details').open=true;$('#person-save').textContent='Save contact changes';dirtyForms.person=true;updateDirty();return;}const b=e.target.closest('[data-delete-person]');if(b)try{await api('/api/person-delete',{id:b.dataset.deletePerson});await renderProfile(id);}catch(e){toast(e.message,true);}};
    $$('[data-person-suggestion]').forEach(b=>b.onclick=()=>{personEdit=null;editingPerson=null;$('#person-save').textContent='Save reviewed public role';const p=detail.suggested_contacts[Number(b.dataset.personSuggestion)];for(const key of ['name','role','email','phone','source','date','excerpt'])$('#person-'+key).value=key==='source'?p.source_url:key==='date'?p.observed_at.slice(0,10):p[key]||'';$('#person-name').closest('details').open=true;dirtyForms.person=true;updateDirty();});
    window.vicallExtended?.open(id);
    $('#rendered-start').onclick=async()=>{try{await api('/api/rendered-audit',{id,url:value('detail-audit-url')||detail.business.websites?.[0]});$('#rendered-result').textContent='Rendered audit started. Refresh the result shortly.';}catch(e){$('#rendered-result').textContent=e.message;}};
    $('#rendered-refresh').onclick=async()=>{try {const report=await(await api('/api/rendered-report?id='+encodeURIComponent(id))).json();$('#rendered-result').innerHTML=`<p>${esc(report.status)} · ${esc(report.message||'')}</p>${report.viewports?report.viewports.map(v=>`<p>${esc(v.name)} · ${v.horizontal_overflow?'Horizontal overflow observed':'No horizontal overflow observed'} · ${v.missing_alt} images missing alt attributes</p><img class="rendered-preview" alt="${esc(v.name)} audit screenshot" src="data:image/png;base64,${v.screenshot_base64}">`).join(''):''}`;}catch(e){$('#rendered-result').textContent=e.message;}};
  }
})();
