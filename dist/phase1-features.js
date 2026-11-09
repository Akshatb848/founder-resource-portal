const sectorUpdates=[
 {id:1,type:'Policy',title:'Battery swapping guidelines updated',summary:'A concise founder brief on operational implications for EV companies.',date:'Today',expires:'28 Oct 2026',source:'Demo Ventures research desk'},
 {id:2,type:'Market',title:'India EV financing activity, Q3 pulse',summary:'Funding patterns and strategic signals for growth-stage mobility companies.',date:'Yesterday',expires:'27 Oct 2026',source:'Approved public sources'},
 {id:3,type:'Regulatory',title:'Data-protection readiness for connected vehicles',summary:'A practical checklist for product and compliance leaders.',date:'24 Sep',expires:'24 Oct 2026',source:'Demo Ventures legal network'}
];
const industryResources=[
 {id:11,cat:'Industry',sub:'Market Research',title:'Industry Market Sizing Workbook',desc:'A guided TAM, SAM and SOM template with source notes and assumption tracking.',type:'XLSX',review:'Reviewed 26 Sep 2026'},
 {id:12,cat:'Industry',sub:'Regulatory & Policy',title:'Regulatory Impact Assessment',desc:'A structured template to translate policy changes into business actions, owners and deadlines.',type:'DOCX',review:'Reviewed 25 Sep 2026'},
 {id:13,cat:'Industry',sub:'Competitive Landscape',title:'Competitive Landscape Map',desc:'A comparison template covering segments, positioning, capabilities, pricing and differentiators.',type:'XLSX',review:'Reviewed 24 Sep 2026'},
 {id:14,cat:'Industry',sub:'Industry Benchmarks',title:'Operating Benchmark Scorecard',desc:'A configurable scorecard for comparing relevant operating indicators with sector reference points.',type:'XLSX',review:'Reviewed 23 Sep 2026'},
 {id:15,cat:'Industry',sub:'Ecosystem & Partnerships',title:'Industry Ecosystem Mapping Canvas',desc:'A practical canvas for mapping regulators, partners, associations, suppliers and strategic channels.',type:'PPTX',review:'Reviewed 22 Sep 2026'}
];
resources.push.apply(resources,industryResources);
var industrySub='All';
function industryResourceCard(r){
 return '<article class="card resource-card"><span class="tag">'+(r.sub?r.sub.toUpperCase():r.cat.toUpperCase())+' · '+r.type+'</span><h3>'+r.title+'</h3><p>'+r.desc+'</p><div class="meta">'+r.review+'</div><div class="card-actions"><button class="btn primary" data-action="download" data-id="'+r.id+'">'+svg('download')+' Download</button><button class="btn ghost" data-action="resource-detail" data-id="'+r.id+'">View details</button></div></article>';
}
function industryResourcesPage(){
 var cats=['All','Legal','Finance','Hiring','Operations','Compliance','Fundraising','Industry'];
 var subs=['All','Market Research','Regulatory & Policy','Competitive Landscape','Industry Benchmarks','Ecosystem & Partnerships'];
 var list=state.resourceFilter==='All'?resources:resources.filter(function(r){return r.cat===state.resourceFilter;});
 if(state.resourceFilter==='Industry'&&industrySub!=='All') list=list.filter(function(r){return r.sub===industrySub;});
 var subnav=state.resourceFilter==='Industry'?'<div class="industry-subsections"><span class="section-label">Industry sub-sections</span><div class="subfilters">'+subs.map(function(s){return '<button class="chip '+(s===industrySub?'active':'')+'" data-industry="'+s+'">'+s+'</button>';}).join('')+'</div></div>':'';
 return head('RESOURCES','Resource Library','Trusted templates, guides and reference material for company-building.','<button class="btn ghost" data-action="suggest-resource">Can’t find it?</button>')+'<div class="filters">'+cats.map(function(c){return '<button class="chip '+(c===state.resourceFilter?'active':'')+'" data-filter="'+c+'">'+c+'</button>';}).join('')+'</div>'+subnav+'<div class="grid cols-3">'+list.map(industryResourceCard).join('')+'</div>';
}
function updatesPage(){
 var cards=sectorUpdates.map(function(u){return '<article class="card update-card"><div class="update-meta"><span class="tag">'+u.type.toUpperCase()+'</span><time>'+u.date+'</time></div><h2>'+u.title+'</h2><p>'+u.summary+'</p><div class="update-foot"><span>Source: '+u.source+'</span><button class="text-btn" data-action="sector-detail" data-id="'+u.id+'">Read brief →</button></div></article>';}).join('');
 return head('CURATED INTELLIGENCE','Sector Updates','Short-lived, relevant signals for electric mobility and energy; picked for your sector.','<button class="btn ghost" data-action="update-settings">Update preferences</button>')+'<div class="updates-layout"><section class="updates-feed">'+cards+'</section><aside class="card update-policy"><span class="eyebrow">CURATION POLICY</span><h2>Useful by design</h2><p>Updates are manually approved, tagged to a sector and link to the original article.</p><ul><li>No general news feed</li><li>No investment-performance data</li><li>No dependency on other internal systems</li><li>Admin can publish or withdraw</li></ul></aside></div>';
}
var adminTab='Approvals';
function adminPage(){
 var tabs=['Approvals','Company mapping','Request routing','Publishing'], body='';
 if(adminTab==='Approvals') body='<div class="data-table"><div class="data-row head"><span>User / company</span><span>Access</span><span>Status</span><span>Action</span></div><div class="data-row"><span>Founder user<br><small>Nimbus Mobility</small></span><span>Founder team</span><span class="status review">Awaiting approval</span><button class="btn primary" data-action="approve-user">Approve</button></div><div class="data-row"><span>Finance user<br><small>Nimbus Mobility</small></span><span>Finance leader</span><span class="status progress">Invited</span><button class="btn ghost">Resend</button></div></div>';
 if(adminTab==='Company mapping') body='<div class="detail-grid"><div><small>Portfolio company</small><strong>Nimbus Mobility</strong></div><div><small>Stage</small><strong>Series B</strong></div><div><small>Relationship partner</small><strong>Dev Malhotra</strong></div><div><small>Current analyst</small><strong>Sara Thomas</strong></div><div><small>Support owner</small><strong>Dev Malhotra</strong></div><div><small>Effective since</small><strong>01 Sep 2026</strong></div></div>';
 if(adminTab==='Request routing') body='<div class="data-table"><div class="data-row head"><span>Category</span><span>Primary route</span><span>Fallback</span><span>SLA</span></div><div class="data-row"><span>Introduction</span><span>Network team</span><span>Dev Malhotra</span><span>2 days</span></div><div class="data-row"><span>Legal / compliance</span><span>Specialist team</span><span>Sara Thomas</span><span>1 day</span></div><div class="data-row"><span>Fundraising</span><span>Investment team</span><span>Dev Malhotra</span><span>1 day</span></div></div>';
 if(adminTab==='Publishing') body='<div class="data-table"><div class="data-row head"><span>Content</span><span>Visibility</span><span>Version</span><span>State</span></div><div class="data-row"><span>MIS Reporting Template</span><span>Portfolio-wide</span><span>v3.2</span><span class="status resolved">Published</span></div><div class="data-row"><span>EV Financing Ecosystem</span><span>Nimbus Mobility</span><span>Sep 2026</span><span class="status resolved">Published</span></div></div>';
 return head('INTERNAL CONTROL PLANE','Admin workspace','Access, ownership, routing and publishing for the Demo Ventures team.','<button class="btn primary" data-action="invite-user">Invite company user</button>')+'<div class="detail-banner">'+svg('shield')+'<span><strong>Internal Demo Ventures view</strong><small>Founders cannot access this workspace in production.</small></span></div><div class="admin-grid"><aside class="card">'+tabs.map(function(t){return '<button class="network-tab '+(t===adminTab?'active':'')+'" data-admin="'+t+'">'+t+'</button>';}).join('')+'</aside><section class="card"><div class="section-title"><h2>'+adminTab+'</h2><button class="btn ghost" data-action="admin-add">+ Add</button></div>'+body+'</section></div>';
}
const dashboardNews=[
 {id:1,label:'POLICY',title:'Battery policy compliance checklist updated',summary:'The Nimbus team should review the refreshed operating checklist and confirm ownership of the applicable actions.',why:'Selected because Nimbus Mobility operates in electric mobility and energy infrastructure.',published:'Today · 9:30 AM',source:'Demo Ventures research desk',expires:'28 Oct 2026'},
 {id:2,label:'MARKET',title:'EV financing activity: Q3 founder brief',summary:'A short view of financing patterns, investor themes and signals relevant to growth-stage mobility businesses.',why:'Selected for Nimbus Mobility’s sector and Series B stage.',published:'Yesterday · 4:15 PM',source:'Approved public sources',expires:'27 Oct 2026'},
 {id:3,label:'REGULATORY',title:'Connected-vehicle data readiness: action note',summary:'Product and compliance teams can use this brief to review data-governance responsibilities and next steps.',why:'Selected for Nimbus Mobility’s connected-energy product context.',published:'24 Sep · 11:00 AM',source:'Demo Ventures legal network',expires:'24 Oct 2026'}
];
const connectDirectory={
 'Operational Support Network':[
  {sub:'Legal Partners',initials:'LG',name:'Legal partner',role:'Corporate and employment law',org:'Demo Ventures partner network',about:'Vetted legal support for portfolio companies.'},
  {sub:'CA & Tax',initials:'CA',name:'CA & tax partner',role:'Chartered accountant and tax advisor',org:'Demo Ventures partner network',about:'Vetted CA support for portfolio companies.'},
  {sub:'Finance & MIS',initials:'FN',name:'Finance partner',role:'Finance operations specialist',org:'Demo Ventures partner network',about:'MIS design, FP&A, board reporting and finance-team setup (sample text).'},
  {sub:'Hiring & HR',initials:'HR',name:'People advisor',role:'Leadership and people advisor',org:'Demo Ventures partner network',about:'Leadership hiring, scorecards, HR policies.'},
  {sub:'Technology & Security',initials:'TC',name:'Technology partner',role:'Technology and security advisor',org:'Demo Ventures partner network',about:'Cloud architecture, security readiness and scaling engineering (sample).'},
  {sub:'Compliance',initials:'CP',name:'Compliance advisor',role:'Regulatory and compliance advisor',org:'Demo Ventures partner network',about:'Corporate compliance and risk programmes.'}
 ],
 'Peer Founder Network':[
  {sub:'Mobility & Energy',initials:'RK',name:'Mobility founder peer',role:'Sector peer conversation',org:'Opt-in founder network',about:'Peer learning on mobility operations, partnerships and scaling.'},
  {sub:'Enterprise GTM',initials:'VP',name:'Enterprise GTM founder',role:'Go-to-market peer',org:'Opt-in founder network',about:'Enterprise sales, account development and predictable pipeline cadence.'},
  {sub:'People & Culture',initials:'SP',name:'People-scale founder',role:'Organisation-building peer',org:'Opt-in founder network',about:'Leadership hiring, culture systems and management cadence.'}
 ],
 'Investor & Fundraising Ecosystem':[
  {sub:'Venture Capital',initials:'VC',name:'Growth-stage VC relationships',role:'Institutional venture capital',org:'Demo Ventures network',about:'Relevant investors matched by stage, sector, geography and mandate.'},
  {sub:'Corporate Venture Capital',initials:'CV',name:'CVC and strategic capital',role:'Corporate venture relationships',org:'Demo Ventures network',about:'Strategic capital relationships connected to mobility, energy and enterprise growth.'},
  {sub:'Investment Banking',initials:'IB',name:'Investment-banking support',role:'Fundraise process support',org:'Demo Ventures network',about:'Process preparation, investor outreach support and transaction coordination.'},
  {sub:'Fundraising Advisors',initials:'FA',name:'Fundraising specialists',role:'Narrative and readiness support',org:'Demo Ventures network',about:'Fundraise narrative, data-room readiness and investor-process guidance.'}
 ],
 'Demo Ventures Network':[
  {sub:'Partners',initials:'DM',name:'Dev Malhotra',role:'Relationship partner',org:'Demo Ventures (fictional)',about:'Portfolio guidance, strategic escalation and partner-level support.'},
  {sub:'Portfolio Managers',initials:'ST',name:'Sara Thomas',role:'Portfolio support owner',org:'Demo Ventures (fictional)',about:'Coordinates founder support, requests and internal follow-through.'},
  {sub:'Advisors & Mentors',initials:'AM',name:'Demo Ventures advisor network',role:'Functional and sector mentors',org:'Demo Ventures (fictional)',about:'Approved advisors and mentors selected for the company’s current needs.'},
  {sub:'Internal Specialist Teams',initials:'DV',name:'Demo Ventures specialist teams',role:'Legal, finance, talent and research support',org:'Demo Ventures (fictional)',about:'Internal specialists who receive requests through the company relationship map.'}
 ]
};
var connectGroup='Operational Support Network',connectSub='All';
function connectPageV2(){
 var groups=Object.keys(connectDirectory),all=connectDirectory[connectGroup],subs=['All'].concat(Array.from(new Set(all.map(function(x){return x.sub;}))));
 var list=connectSub==='All'?all:all.filter(function(x){return x.sub===connectSub;});
 var cards=list.map(function(p){var action=connectGroup==='Demo Ventures Network'?'Request support':'Request introduction';return '<article class="card network-card"><div class="provider-head"><div class="avatar">'+p.initials+'</div><div><h3>'+p.name+'</h3><p>'+p.role+'</p></div></div><span class="tag">'+p.sub.toUpperCase()+'</span><p>'+p.about+'</p><div class="network-card-foot"><small>'+p.org+'</small><button class="btn primary wide" data-action="network-intro" data-person="'+p.name+'" data-group="'+connectGroup+'">'+svg('send')+' '+action+'</button></div></article>';}).join('');
 return head('NETWORK','Connect','Access operating specialists, portfolio peers, fundraising relationships and the Demo Ventures team through one controlled introduction process.','<button class="btn primary" data-action="connect-help">Help me choose</button>')+
 '<div class="connect-group-tabs" role="tablist" aria-label="Connection networks">'+groups.map(function(g){return '<button class="connect-group-tab '+(g===connectGroup?'active':'')+'" role="tab" aria-selected="'+(g===connectGroup)+'" data-connect-group="'+g+'">'+g+'</button>';}).join('')+'</div>'+
 '<div class="connect-subsection"><span class="section-label">'+connectGroup+' sub-sections</span><div class="subfilters">'+subs.map(function(s){return '<button class="chip '+(s===connectSub?'active':'')+'" data-connect-sub="'+s+'">'+s+'</button>';}).join('')+'</div></div>'+
 ''+
 '<div class="grid cols-3">'+cards+'</div>';
}
const originalDashboard=pages.dashboard;
function dashboardNewsBar(){
 return '<section class="news-flash" aria-label="Important sector news for Nimbus Mobility"><div class="news-flash-label"><span class="pulse-dot"></span><span><strong>NEWS FLASHES</strong><small>Selected for Nimbus Mobility</small></span></div><div class="news-flash-items">'+dashboardNews.map(function(n){var e=function(x){return String(x==null?'':x).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});};return '<button class="news-flash-item" data-dashboard-news="'+e(n.id)+'" aria-label="Read more: '+e(n.title)+'"><span>'+e(n.label)+'</span><strong>'+e(n.title)+'</strong><small>'+e(n.published)+'</small></button>';}).join('')+'</div><button class="news-flash-all" data-goto="updates">View all <span aria-hidden="true">→</span></button></section>';
}
pages.dashboard=function(){return dashboardNewsBar()+originalDashboard();};
pages.updates=updatesPage;
pages.admin=adminPage;
pages.resources=industryResourcesPage;
pages.connect=connectPageV2;
document.addEventListener('click',function(e){
 var el=e.target.closest('[data-admin],[data-industry],[data-dashboard-news],[data-connect-group],[data-connect-sub],[data-action="network-intro"],[data-action="sector-detail"],[data-action="update-settings"],[data-action="approve-user"],[data-action="invite-user"],[data-action="admin-add"]');
 if(!el)return;
 if(el.dataset.admin){adminTab=el.dataset.admin;render('admin');return;}
 if(el.dataset.industry){industrySub=el.dataset.industry;render('resources');return;}
 if(el.dataset.connectGroup){connectGroup=el.dataset.connectGroup;connectSub='All';render('connect');return;}
 if(el.dataset.connectSub){connectSub=el.dataset.connectSub;render('connect');return;}
 if(el.dataset.action==='network-intro'){requestModal((connectGroup==='Demo Ventures Network'?'Support from ':'Introduction to ')+el.dataset.person+' · '+el.dataset.group);}
 if(el.dataset.dashboardNews){var n=dashboardNews.find(function(x){return x.id==el.dataset.dashboardNews;});modal(n.title,'<div class="news-detail-meta"><span class="tag">'+n.label+'</span><span>'+n.published+'</span></div><p class="lead">'+n.summary+'</p><div class="detail-grid"><div><small>Picked by</small><strong>'+n.source+'</strong></div><div><small>Visible until</small><strong>'+n.expires+'</strong></div></div>','Mark as read',function(){toast('News flash marked as read');});}
 if(el.dataset.action==='sector-detail'){var u=sectorUpdates.find(function(x){return x.id==el.dataset.id;});modal(u.title,'<span class="tag">'+u.type.toUpperCase()+'</span><p>'+u.summary+'</p>','Mark as read',function(){toast('Sector update marked as read');});}
 if(el.dataset.action==='update-settings')toast('Sector-update preferences saved');
 if(el.dataset.action==='approve-user'){el.closest('.data-row').querySelector('.status').textContent='Approved';toast('Company user approved');}
 if(el.dataset.action==='invite-user')modal('Invite company user','<label>Company<input value="Nimbus Mobility" readonly></label><label>Email address<input type="email" required placeholder="name@example.com"></label><label>Access role<select><option>Founder</option><option>Finance leader</option><option>HR leader</option><option>Company team member</option></select></label>','Send invitation',function(){toast('Invitation queued for administrator review');});
 if(el.dataset.action==='admin-add')toast('Admin create flow demonstrated');
});
