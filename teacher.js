import { getAllScores } from './firebase.js';

const TEACHER_PASSWORD = 'teacher123';
let allScores = [];

// Level mapping: id -> { name, level }
const LEVEL_MAP = {
  1:  { name: 'Our Environment',           level: 'beginner' },
  2:  { name: 'Foundations of Ecology',    level: 'beginner' },
  3:  { name: "Earth's Natural Resources", level: 'beginner' },
  4:  { name: 'Climate & Weather Basics',  level: 'beginner' },
  5:  { name: 'Climate Change Science',    level: 'intermediate' },
  6:  { name: 'Biodiversity & Conservation', level: 'intermediate' },
  7:  { name: 'Pollution & Its Control',   level: 'intermediate' },
  8:  { name: 'Waste Management & Recycling', level: 'intermediate' },
  9:  { name: 'Sustainable Living',        level: 'intermediate' },
  10: { name: 'Renewable Energy Systems', level: 'advanced' },
  11: { name: 'Forests, Oceans & Wildlife', level: 'advanced' },
  12: { name: 'Environmental Policy & Law', level: 'advanced' },
  13: { name: 'Green Technology & Innovation', level: 'advanced' },
  14: { name: 'Climate Action & Advocacy', level: 'expert' },
  15: { name: 'Environmental Project Mgmt', level: 'expert' },
  16: { name: 'Environmental Ethics & Justice', level: 'expert' },
  17: { name: 'Capstone: EcoChronicles Missions', level: 'expert' },
};

function getLevelInfo(levelField) {
  // levelField could be a number (1-17) or old string like "beginner-1"
  if (!levelField) return { name: '—', level: 'unknown', display: '—' };
  const num = parseInt(levelField);
  if (!isNaN(num) && LEVEL_MAP[num]) {
    const info = LEVEL_MAP[num];
    return { name: info.name, level: info.level, display: `L${num}: ${info.name}` };
  }
  // fallback for old format
  return { name: String(levelField), level: String(levelField).split('-')[0] || 'beginner', display: String(levelField) };
}

function teacherLogin() {
  const pass = document.getElementById('teacher-pass').value;
  if (pass === TEACHER_PASSWORD) {
    showScreen('dashboard');
    loadScores();
  } else {
    alert('Wrong password! Try: teacher123');
  }
}

function teacherLogout() {
  document.getElementById('teacher-pass').value = '';
  showScreen('teacher-login');
}

async function loadScores() {
  const lang = window.currentLang || 'en';
  document.getElementById('scores-body').innerHTML =
    `<tr><td colspan="8" class="loading-row">${lang === 'ta' ? 'மதிப்பெண்கள் ஏற்றப்படுகின்றன...' : 'Loading scores...'}</td></tr>`;
  allScores = await getAllScores();
  applyFilters();
  updateStats(allScores);
}

function updateStats(scores) {
  const uniqueStudents = new Set(scores.map(s => s.name)).size;
  const totalAttempts  = scores.length;
  const avgScore = scores.length
    ? Math.round(scores.reduce((sum, s) => sum + (s.score / s.total) * 100, 0) / scores.length)
    : 0;
  const perfectScores = scores.filter(s => s.score === s.total).length;

  document.getElementById('stat-students').textContent = uniqueStudents;
  document.getElementById('stat-attempts').textContent = totalAttempts;
  document.getElementById('stat-avg').textContent      = avgScore + '%';
  document.getElementById('stat-perfect').textContent  = perfectScores;
}

function applyFilters() {
  const levelFilter = document.getElementById('filter-level').value;
  const langFilter  = document.getElementById('filter-lang').value;
  const perfFilter  = document.getElementById('filter-perf').value;

  let filtered = allScores;

  if (levelFilter !== 'all') {
    filtered = filtered.filter(s => {
      const info = getLevelInfo(s.level);
      return info.level === levelFilter;
    });
  }
  if (langFilter !== 'all') {
    filtered = filtered.filter(s => (s.language || 'en') === langFilter);
  }
  if (perfFilter !== 'all') {
    filtered = filtered.filter(s => {
      const pct = Math.round((s.score / s.total) * 100);
      if (perfFilter === 'perfect') return s.score === s.total;
      if (perfFilter === 'good')    return pct >= 60 && s.score !== s.total;
      if (perfFilter === 'low')     return pct < 60;
      return true;
    });
  }

  renderTable(filtered);
}

function renderTable(scores) {
  const tbody = document.getElementById('scores-body');
  if (scores.length === 0) {
    const lang = window.currentLang || 'en';
    tbody.innerHTML = `<tr><td colspan="8" class="no-data">${lang === 'ta' ? 'மதிப்பெண்கள் இல்லை. மாணவர்களிடம் வினாடி வினாவை முடிக்கச் சொல்லுங்கள்!' : 'No scores found. Ask students to complete quizzes!'}</td></tr>`;
    return;
  }

  tbody.innerHTML = scores.map((s, i) => {
    const pct = Math.round((s.score / s.total) * 100);

    // Performance badge (bilingual)
    const lang = window.currentLang || 'en';
    let badgeClass = 'badge-try', badgeText = lang === 'ta' ? '💪 மேலும் முயற்சி' : '💪 Keep Trying';
    if (s.score === s.total)   { badgeClass = 'badge-perfect'; badgeText = lang === 'ta' ? '🌟 சிறப்பு' : '🌟 Perfect'; }
    else if (pct >= 60)        { badgeClass = 'badge-good';    badgeText = lang === 'ta' ? '✅ நல்லது' : '✅ Good'; }

    // Level info
    const info = getLevelInfo(s.level);
    const levelColors = {
      beginner: 'diff-beginner',
      intermediate: 'diff-intermediate',
      advanced: 'diff-advanced',
      expert: 'diff-expert',
    };
    const diffClass = levelColors[info.level] || 'diff-beginner';
    const levelDisplay = info.display;

    // Date
    const date = s.timestamp
      ? new Date(s.timestamp).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' })
      : 'N/A';

    const langLabel = s.language === 'ta'
      ? (lang === 'ta' ? 'தமிழ்' : 'Tamil')
      : (lang === 'ta' ? 'ஆங்கிலம்' : 'English');
    const studentClass = s.studentClass || '—';

    return `
      <tr>
        <td>${i + 1}</td>
        <td><strong>${s.name}</strong></td>
        <td>${studentClass}</td>
        <td><span class="diff-pill ${diffClass}">${levelDisplay}</span></td>
        <td><strong>${s.score} / ${s.total}</strong> (${pct}%)</td>
        <td><span class="badge ${badgeClass}">${badgeText}</span></td>
        <td><span class="lang-pill">${langLabel}</span></td>
        <td>${date}</td>
      </tr>`;
  }).join('');
}

function showScreen(id) {
  document.querySelectorAll('.screen').forEach(s => s.classList.add('hidden'));
  document.getElementById(id).classList.remove('hidden');
}

// ===== DOWNLOAD REPORT (client-side CSV — no Storage/Functions needed) =====
function downloadReportCSV() {
  if (!allScores.length) { alert('No scores to export yet.'); return; }
  const header = ['#', 'Student Name', 'Class', 'Level', 'Score', 'Total', 'Percentage', 'Language', 'Date & Time'];
  const rows = allScores.map((s, i) => {
    const info = getLevelInfo(s.level);
    const pct = s.total ? Math.round((s.score / s.total) * 100) : 0;
    const date = s.timestamp ? new Date(s.timestamp).toLocaleString('en-IN') : 'N/A';
    return [i + 1, s.name || '', s.studentClass || '', info.display, s.score, s.total, pct + '%', s.language === 'ta' ? 'Tamil' : 'English', date];
  });
  const csv = [header, ...rows]
    .map(row => row.map(cell => `"${String(cell).replace(/"/g, '""')}"`).join(','))
    .join('\r\n');
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `EcoChronicles_Class_Report_${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
window.downloadReportCSV = downloadReportCSV;

window.teacherLogin  = teacherLogin;
window.teacherLogout = teacherLogout;
window.loadScores    = loadScores;
window.applyFilters  = applyFilters;
// ===== TAB SWITCHING =====
let currentTab = 'all';

function switchTab(tab) {
  currentTab = tab;
  ['all','ta','ai','activities'].forEach(t=>{
    const btn = document.getElementById('tab-'+t);
    if(btn) btn.classList.toggle('active', tab===t);
    const panel = document.getElementById('panel-'+t);
    if(panel) panel.style.display = tab===t ? '' : 'none';
  });
  if (tab === 'ta') renderTamilPanel();
  if (tab === 'ai' && window.TeacherAI) window.TeacherAI.renderAnalytics(allScores);
  if (tab === 'activities' && window.TeacherAI) window.TeacherAI.renderWasteLog();
}

function renderTamilPanel() {
  const lang = window.currentLang || 'en';
  const tamilScores = allScores.filter(s => (s.language || 'en') === 'ta');

  // Stats
  const uniqueTa = new Set(tamilScores.map(s => s.name)).size;
  const avgTa = tamilScores.length
    ? Math.round(tamilScores.reduce((sum, s) => sum + (s.score / s.total) * 100, 0) / tamilScores.length)
    : 0;
  const perfectTa = tamilScores.filter(s => s.score === s.total).length;

  // Top performer (highest avg pct)
  const studentMap = {};
  tamilScores.forEach(s => {
    if (!studentMap[s.name]) studentMap[s.name] = { total: 0, earned: 0 };
    studentMap[s.name].earned += s.score;
    studentMap[s.name].total += s.total;
  });
  let topName = '—';
  let topPct = -1;
  Object.entries(studentMap).forEach(([name, d]) => {
    const pct = d.total ? Math.round((d.earned / d.total) * 100) : 0;
    if (pct > topPct) { topPct = pct; topName = name; }
  });

  document.getElementById('ta-stat-count').textContent = uniqueTa;
  document.getElementById('ta-stat-avg').textContent = avgTa + '%';
  document.getElementById('ta-stat-perfect').textContent = perfectTa;
  document.getElementById('ta-stat-top').textContent = topName !== '—' ? topName.split(' ')[0] : '—';

  // Table
  const tbody = document.getElementById('ta-scores-body');
  if (tamilScores.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" class="no-data">${
      lang === 'ta'
        ? 'தமிழில் வினாடி வினா முடிக்கிய மாணவர்கள் இல்லை!'
        : 'No Tamil learners yet — ask students to switch to தமிழ் and complete a quiz!'
    }</td></tr>`;
    return;
  }

  tbody.innerHTML = tamilScores.map((s, i) => {
    const pct = Math.round((s.score / s.total) * 100);
    let badgeClass = 'badge-try',  badgeText = lang === 'ta' ? '💪 மேலும் முயற்சி' : '💪 Keep Trying';
    if (s.score === s.total)  { badgeClass = 'badge-perfect'; badgeText = lang === 'ta' ? '🌟 சிறப்பு' : '🌟 Perfect'; }
    else if (pct >= 60)       { badgeClass = 'badge-good';    badgeText = lang === 'ta' ? '✅ நல்லது'  : '✅ Good'; }

    const info = getLevelInfo(s.level);
    const levelColors = { beginner:'diff-beginner', intermediate:'diff-intermediate', advanced:'diff-advanced', expert:'diff-expert' };
    const diffClass = levelColors[info.level] || 'diff-beginner';

    const date = s.timestamp
      ? new Date(s.timestamp).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' })
      : 'N/A';

    return `
      <tr>
        <td>${i + 1}</td>
        <td><strong>${s.name}</strong></td>
        <td>${s.studentClass || '—'}</td>
        <td><span class="diff-pill ${diffClass}">${info.display}</span></td>
        <td><strong>${s.score} / ${s.total}</strong> (${pct}%)</td>
        <td><span class="badge ${badgeClass}">${badgeText}</span></td>
        <td>${date}</td>
      </tr>`;
  }).join('');
}

window.switchTab = switchTab;
