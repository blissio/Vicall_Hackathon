'use strict';
// Website analysis is kept separate from manual research decisions.
(() => {
  let auditJob = {status: 'idle', completed: 0, total: 0};
  let lastProgress = '';
  let auditPage = 1;
  let auditRows = [];
  let auditTimer;
  let detailReport = null;
  let detailRequest = 0;
  const gradeLabels = {strong: 'Strong basics', review: 'Needs review', needs_work: 'Needs work', partial: 'Partial audit', unknown: 'No SEO grade'};
  const reachLabels = {reachable: 'Reachable HTML', unreachable: 'Connection failed', http_error: 'HTTP error', restricted: 'Access restricted', unknown: 'Inconclusive', non_html: 'Non-HTML response'};

  function matches(row, filter) {
    const audit = row.audit;
    if (!filter) return true;
    if (filter === 'unaudited') return !audit;
    if (!audit) return false;
    if (filter === 'reachable') return audit.reachability === 'reachable';
    if (filter === 'unreachable') return ['unreachable', 'http_error'].includes(audit.reachability);
    if (filter === 'inconclusive') return !['reachable', 'unreachable', 'http_error'].includes(audit.reachability);
    if (filter === 'stale') return Date.now() - new Date(audit.checked_at).getTime() > 7 * 86400000;
    return audit.grade === filter;
  }

  function cell(row) {
    if (auditJob.status === 'running' && auditJob.ids?.includes(row._id) && !auditJob.results?.some(r => r.id === row._id)) {
      return '<span class="seo-badge seo-pending">Queued / analyzing</span>';
    }
    const a = row.audit;
    if (!a) return '<span class="muted-cell">Not analyzed</span>';
    return `<button class="seo-badge seo-${esc(a.grade)}" data-audit-open="${esc(row._id)}" title="${esc(date(a.checked_at))}">${a.score == null ? '' : `${a.score} · `}${gradeLabels[a.grade] || 'Inconclusive'}</button>`;
  }

  function render() {
    const audited = state.rows.filter(r => r.audit);
    const reachable = audited.filter(r => r.audit.reachability === 'reachable');
    const weak = audited.filter(r => ['needs_work','review'].includes(r.audit.grade));
    const uncertain = audited.filter(r => r.audit.score == null);
    $('#nav-audits').textContent = count(audited.length);
    $('#audit-stats').innerHTML = [
      ['Businesses analyzed',audited.length,'link','Saved results with source URLs'],
      ['Reachable HTML',reachable.length,'check','Observed from this computer'],
      ['SEO to review',weak.length,'search','Needs work or review · checklist only'],
      ['No SEO grade',uncertain.length,'data','Blocked, failed, partial, or non-HTML']
    ].map(([label,value,image,foot])=>`<article class="stat-card"><div class="stat-label">${label}${icon(image)}</div><div class="stat-value">${count(value)}</div><div class="stat-foot">${foot}</div></article>`).join('');
    const directoryIds = new Set(state.filtered.map(r => r._id));
    auditRows = audited.filter(r => directoryIds.has(r._id) && matches(r,$('#audit-lab-filter').value))
      .sort((a,b) => (b.audit.checked_at || '').localeCompare(a.audit.checked_at || ''));
    const total = auditRows.length, pages = Math.max(1,Math.ceil(total/15));
    auditPage = Math.min(auditPage,pages);
    $('#audit-results-count').textContent = count(total);
    $('#audit-match-summary').textContent = `${count(state.filtered.length)} businesses match the current directory filters`;
    $('#audit-results').innerHTML = auditRows.slice((auditPage-1)*15,auditPage*15).map(r => {
      const a = r.audit;
      let host = a.requested_url;
      try {host = new URL(host).hostname;} catch {}
      return `<article class="audit-result-row"><div class="audit-business"><button class="business-name" data-audit-open="${esc(r._id)}">${esc(r.name)}</button><p>${esc(host)} · ${esc(categoryName(r))}</p></div><div><span class="reach-badge reach-${esc(a.reachability)}">${reachLabels[a.reachability] || 'Inconclusive'}</span>${a.http_status ? `<small>HTTP ${a.http_status}</small>` : ''}</div><div>${cell(r)}</div><div class="audit-checked">${esc(date(a.checked_at))}</div><button class="icon-button" data-audit-open="${esc(r._id)}" aria-label="View website audit for ${esc(r.name)}">${icon('arrow')}</button></article>`;
    }).join('') || `<div class="empty-state"><svg class="icon"><use href="#i-link"/></svg><h3>${audited.length ? 'No audits match these filters' : 'Make the first website check'}</h3><p>${audited.length ? 'Adjust the directory filters or the findings filter.' : 'Open a business profile to analyze its listed or newly discovered website.'}</p></div>`;
    $('#audit-page-summary').textContent = total ? `${count((auditPage-1)*15+1)}–${count(Math.min(auditPage*15,total))} of ${count(total)} findings` : 'No findings to display';
    $('#audit-page-number').textContent = `${auditPage} / ${pages}`;
    $('#audit-previous').disabled = auditPage <= 1;
    $('#audit-next').disabled = auditPage >= pages;
    $('#audit-export').disabled = !total;
    const running = auditJob.status === 'running';
    ['audit-filtered','audit-shortlist','audit-selected','detail-run-audit'].forEach(id => $('#'+id).disabled=running);
    $('#detail-run-audit').textContent = running && auditJob.ids?.includes(state.detail) ? 'Checking…' : 'Analyze';
  }

  function renderProgress(job) {
    auditJob = job;
    $('#audit-job-message').textContent = job.message || 'Ready to analyze websites';
    $('#audit-progress-dot').className = 'job-dot ' + job.status;
    $('#audit-job-detail').textContent = job.status === 'idle' ? 'Select businesses or open a profile to check a specific website.' : `${job.completed || 0} of ${job.total || 0} checks completed · ${job.skipped || 0} skipped${job.error ? ` · ${job.error}` : ''}`;
    $('#audit-cancel').hidden = job.status !== 'running';
    const key = `${job.started_at}:${job.completed}:${job.status}`;
    if (key !== lastProgress) {
      for (const update of job.results || []) {
        const row = state.rows.find(r => r._id === update.id);
        if (row) row.audit = update.audit;
      }
      if (state.detail && job.results?.some(r => r.id === state.detail)) openReport(state.detail,false);
      filterRows();
      lastProgress = key;
    }
  }

  async function start(ids, url, force = $('#audit-force').checked) {
    if (auditJob.status === 'running') return toast('Wait for the current batch, or stop it after the current website.');
    if (!ids.length) return toast('Choose a business with a website, or enter a URL in its profile.');
    if (ids.length > 25) return toast('Choose up to 25 businesses per batch.',true);
    try {
      const job = await (await api('/api/audit',{ids,force,...(url ? {url} : {})})).json();
      renderProgress(job);
      toast(job.status === 'running' ? `Website analysis started · ${job.total} checks` : job.message);
      clearTimeout(auditTimer);
      auditTimer = setTimeout(poll,700);
    } catch(e) {toast(e.message,true);}
  }

  async function poll() {
    try {
      const previous = auditJob;
      const job = await (await api('/api/audit-job')).json();
      renderProgress(job);
      if (previous.status === 'running' && job.status !== 'running') toast(job.message,job.status==='failed');
    } catch(e) {
      if (auditJob.status === 'running') toast('Could not read audit progress. Check that the Python app is running.',true);
    } finally {auditTimer=setTimeout(poll,auditJob.status==='running'?1800:8000);}
  }

  async function openReport(id, resetURL=true) {
    const row = state.rows.find(r=>r._id===id);
    if (!row) return;
    if (resetURL) {
      $('#detail-audit-url').value = row.audit?.requested_url || row.websites?.[0] || '';
      $('#detail-audit-report').innerHTML = '<p class="small-muted">Loading saved website findings…</p>';
    }
    const request = ++detailRequest;
    try {
      const report = await (await api('/api/audit-report?id='+encodeURIComponent(id))).json();
      if (state.detail !== id || request !== detailRequest) return;
      detailReport = report;
      renderReport(report);
    } catch(e) {if(state.detail===id && request===detailRequest)$('#detail-audit-report').textContent=e.message;}
  }

  function renderReport(report) {
    const a=report.latest;
    if (!a) {
      $('#detail-audit-report').innerHTML='<div class="audit-placeholder">No website analysis yet. Enter a public URL above and choose Analyze.</div>';
      return;
    }
    const fixes=a.recommendations || [];
    const flags = a.checks?.filter(c=>c.status==='critical').length;
    const coverage = a.score_coverage;
    const score = a.score==null ? '—' : a.score;
    const metadata=[['Checked',date(a.checked_at)],['HTTP response',a.http_status || 'Not confirmed'],['Fetch time',a.fetch_ms == null ? 'Not measured' : `${count(a.fetch_ms)} ms · one sample`],['URL source',a.target_source==='user_supplied'?'Entered by researcher':'Listed in OpenStreetMap'],['Audit version',a.audit_version || 'Unknown']];
    $('#detail-audit-report').innerHTML=`
      <div class="audit-score-card"><div><div class="card-kicker">TECHNICAL SEO CHECKLIST</div><div class="audit-grade">${esc(gradeLabels[a.grade] || 'Inconclusive')}</div><span class="reach-badge reach-${esc(a.reachability)}">${esc(reachLabels[a.reachability] || 'Inconclusive')}</span></div><div class="score-value">${score}<small>${a.score==null?'not scored':'/ 100'}</small></div></div>
      <p class="audit-message">${esc(a.message)}</p>
      ${flags?`<div class="audit-critical">An indexing blocker was observed.${a.score==null?'':' The checklist score is capped at 49.'} Verify whether the restriction is intentional.</div>`:''}
      ${coverage!=null&&coverage<100?`<p class="small-muted">${coverage}% of weighted checks were conclusive. Unknown checks are excluded; a truncated page is not scored.</p>`:''}
      <div class="audit-url-evidence"><span>Requested</span>${externalLink(a.requested_url,a.requested_url)}${a.final_url?`<span>Final URL</span>${externalLink(a.final_url,a.final_url)}`:''}</div>
      <dl class="definition-list audit-meta">${metadata.map(([label,value])=>`<div><dt>${label}</dt><dd>${esc(value)}</dd></div>`).join('')}</dl>
      <h4 class="audit-subheading">Suggested improvements</h4>
      <ol class="audit-fixes">${fixes.length?fixes.map(c=>`<li><strong>${esc(c.label)}</strong><p>${esc(c.recommendation)}</p></li>`).join(''):'<li><strong>No failing weighted checks observed</strong><p>Confirm site ownership and review rendered pages, content quality, mobile usability, and performance before calling the SEO strong overall.</p></li>'}</ol>
      <details class="audit-check-details"><summary>Evidence for ${a.checks?.length || 0} checks</summary>${(a.checks || []).map(c=>`<article class="audit-check check-${esc(c.status)}"><div><span class="check-status">${esc(c.status)}</span><strong>${esc(c.label)}</strong>${c.weight ? `<small>${c.weight} pts</small>` : '<small>Advisory</small>'}</div><p>${esc(c.evidence)}</p></article>`).join('')}</details>
      ${a.redirects?.length?`<details class="audit-check-details"><summary>${a.redirects.length} redirects observed</summary>${a.redirects.map(r=>`<p class="small-muted">HTTP ${r.status}: ${esc(r.from)} → ${esc(r.to)}</p>`).join('')}</details>`:''}
      <details class="audit-check-details"><summary>Audit limits & scoring</summary><p class="small-muted">HTTPS 10 · title 20 · description 15 · H1 15 · viewport 10 · indexing 15 · canonical 5 · alt attributes 5 · internal links 5. 80+ = strong basics, 50–79 = needs review, under 50 = needs work. Advisory checks do not change the score.</p><ul class="audit-limits">${(a.limitations || ['A blocked or failed check does not establish poor SEO.','Business website identity remains unverified.']).map(l=>`<li>${esc(l)}</li>`).join('')}</ul></details>
      <details class="audit-check-details"><summary>Previous checks (${report.history?.length || 0})</summary>${(report.history || []).map(h=>`<div class="audit-history-row"><span>${esc(date(h.checked_at))}</span><span>${h.score==null?'No grade':`${h.score}/100`}</span><small>${esc(reachLabels[h.reachability] || h.reachability)}</small></div>`).join('') || '<p class="small-muted">Previous results appear after a recheck. Up to four previous results are retained.</p>'}</details>
      <button id="download-audit-report" class="button secondary audit-download">${icon('download')}Download evidence report</button>`;
  }

  function eligible(rows) {
    return rows.filter(r=> {
      if (!r.websites?.length && !r.audit?.requested_url) return false;
      if ($('#audit-force').checked || !r.audit || r.audit.audit_version !== state.auditVersion) return true;
      const age = Date.now()-new Date(r.audit.checked_at).getTime();
      return !Number.isFinite(age) || age < 0 || age >= 86400000;
    }).map(r=>r._id);
  }
  $('#audit-filtered').addEventListener('click',()=>start(eligible(state.filtered).slice(0,25)));
  $('#audit-shortlist').addEventListener('click',()=>start(eligible(state.rows.filter(r=>r.workflow.shortlisted)).slice(0,25)));
  $('#audit-selected').addEventListener('click',()=>start([...state.selected]));
  $('#detail-run-audit').addEventListener('click',()=>{
    const url=$('#detail-audit-url').value.trim();
    if (!url) return toast('Enter a website URL to analyze.',true);
    start([state.detail],url,true);
  });
  $('#audit-cancel').addEventListener('click',async()=>{try{renderProgress(await (await api('/api/audit-cancel',{})).json());}catch(e){toast(e.message,true);}});
  $('#audit-lab-filter').addEventListener('change',()=>{auditPage=1;render();});
  $('#audit-clear-directory').addEventListener('click',resetFilters);
  $('#audit-previous').addEventListener('click',()=>{auditPage--;render();});
  $('#audit-next').addEventListener('click',()=>{auditPage++;render();});
  $('#audit-export').addEventListener('click',()=>exportRows(auditRows.map(r=>r._id)));
  document.addEventListener('click',e=>{
    const button=e.target.closest('[data-audit-open]');
    if (button) {
      openDetail(button.dataset.auditOpen);
      if(state.detail===button.dataset.auditOpen) $('#detail-audit-section').scrollIntoView({block:'start'});
    }
    if(e.target.closest('#download-audit-report') && detailReport?.latest){
      const blob=new Blob([JSON.stringify(detailReport,null,2)],{type:'application/json'});
      const url=URL.createObjectURL(blob),link=document.createElement('a');
      link.href=url;link.download='vicall-website-evidence.json';document.body.appendChild(link);link.click();link.remove();
      setTimeout(()=>URL.revokeObjectURL(url),60000);
      toast('Website evidence report exported');
    }
  });
  window.vicallAudit={matches,cell,render,open:openReport};
  render();poll();
})();
