// Theme toggle — save to DB
function toggleTheme(){
    var html=document.documentElement;
    var next=html.getAttribute('data-theme')==='dark'?'light':'dark';
    html.setAttribute('data-theme',next);
    fetch('/api/preferences/theme',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({theme:next})});
}

// Sidebar pin toggle — save to DB
function toggleSidebarPin(){
    var sidebar=document.getElementById('sidebar');
    if(!sidebar)return;
    sidebar.classList.toggle('pinned');
    var pinned=sidebar.classList.contains('pinned');
    var content=document.querySelector('.content');
    if(content){content.style.marginLeft=pinned?'260px':'60px';}
    fetch('/api/preferences/sidebar',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pinned:pinned})});
}

// Timezone select — save to DB & reload
function setTimezone(val){
    fetch('/api/preferences/timezone',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({timezone_offset:parseInt(val)})})
    .then(function(){ location.reload(); });
}

// Login toggle
function toggleLogin(){
    var f=document.getElementById('localLoginForm');
    if(f) f.style.display=f.style.display==='none'?'block':'none';
}
