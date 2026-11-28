/* global results.js — EEECi FA'26 Live Leaderboard */
(function () {
  'use strict';

  /* ---- State ---- */
  var latestState = {};
  var expandedTeamId = null;
  var pollTimer = null;

  /* ---- DOM helpers ---- */
  function el(id) { return document.getElementById(id); }
  function setText(id, v) { var e = el(id); if (e) e.textContent = v; }
  function setHTML(id, v) { var e = el(id); if (e) e.innerHTML = v; }

  /* ---- WebSocket connection (REST fallback) ---- */
  function connect() {
    // Primary: REST polling — /api/state is public, no auth required
    startPolling();
  }

  function startPolling() {
    if (pollTimer) return;
    fetchState();
    pollTimer = setInterval(fetchState, 1500);
  }

  function fetchState() {
    fetch('/api/state', { credentials: 'same-origin' })
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function (data) {
        setWsStatus('live');
        renderAll(data);
      })
      .catch(function () {
        setWsStatus('reconnecting');
      });
  }

  function setWsStatus(status) {
    var pill = el('wsStatus');
    if (!pill) return;
    if (status === 'live') {
      pill.textContent = 'LIVE';
      pill.className = 'res-ws-pill live';
    } else {
      pill.textContent = 'RECONNECTING';
      pill.className = 'res-ws-pill reconnecting';
    }
  }

  /* ---- Master render ---- */
  function renderAll(state) {
    latestState = state || {};
    var progress = (state && state.tournament_progress) || {};
    renderProgressBar(progress);
    renderLiveMatch(state, progress);
    renderHighlights(progress);
    renderLeaderboard(progress.standings || [], state);
    renderBracket(progress);
    renderMatchResults(progress);
  }

  /* ---- Progress bar ---- */
  function renderProgressBar(progress) {
    var done = progress.completed_matches || 0;
    var total = progress.total_matches || 14;
    var pct = progress.percent_complete || 0;
    setText('progressText', 'Match ' + done + ' of ' + total + ' \u2022 ' + pct + '%');
    var bar = el('progressBar');
    if (bar) bar.style.width = pct + '%';
  }

  /* ---- Live match ticker ---- */
  function renderLiveMatch(state, progress) {
    var highlights = progress.highlights || {};
    var live = highlights.live_match;
    var card = el('liveMatchCard');
    if (!card) return;
    if (!live) {
      card.classList.add('hidden');
      return;
    }
    card.classList.remove('hidden');
    var mn = String(live.match_number || 1).padStart(2, '0');
    setText('liveMatchLabel', 'MATCH ' + mn);
    setText('liveTeamA', live.team_a_name || 'Team A');
    setText('liveTeamB', live.team_b_name || 'Team B');
    setText('liveScoreA', String(live.score_a || 0));
    setText('liveScoreB', String(live.score_b || 0));
    var phase = (live.phase || 'IN PROGRESS').replace(/_/g, ' ');
    setText('livePhaseBadge', phase);
  }

  /* ---- Highlights ---- */
  function renderHighlights(progress) {
    var h = progress.highlights || {};
    // Highest match score
    var hms = h.highest_match_score;
    setText('hlHighestScoreVal', hms ? String(hms.score) : '--');
    setText('hlHighestScoreSub', hms ? (hms.team_name + ' \u2022 M' + String(hms.match_number || '').padStart(2, '0')) : '--');
    // RF leader
    var rf = h.top_rapid_fire_team;
    setText('hlRFLeaderVal', rf ? rf.name : '--');
    setText('hlRFLeaderSub', rf ? (rf.points + ' pts') : '-- pts');
    // Buzzer leader
    var bz = h.top_buzzer_team;
    setText('hlBuzzerLeaderVal', bz ? bz.name : '--');
    setText('hlBuzzerLeaderSub', bz ? (bz.points + ' pts') : '-- pts');
  }

  /* ---- Leaderboard ---- */
  function renderLeaderboard(standings, state) {
    var tbody = el('leaderboardBody');
    if (!tbody) return;
    if (!standings || !standings.length) {
      tbody.innerHTML = '<tr><td colspan="10" style="text-align:center;padding:2rem;color:var(--text-muted);">No team data yet.</td></tr>';
      return;
    }

    var progress = (state && state.tournament_progress) || {};
    var wildCards = progress.wild_cards || [];
    // Determine cutoff: insert divider after the last team that has wins but no advancing status,
    // before pure-eliminated teams. Use wild_card cutoff after rank=2 qualifier positions.
    // Simple rule: insert WC cutoff divider after the 2nd team in standings that is WILD_CARD qualified.
    var wcCutoffInserted = false;
    var wcTeamsShown = 0;

    var rows = '';
    for (var i = 0; i < standings.length; i++) {
      var s = standings[i];
      var rank = s.rank || (i + 1);
      var isLive = s.in_live_match;
      var rowClass = isLive ? 'row-live' : '';
      if (expandedTeamId === s.team_id) rowClass += ' row-expanded';

      // Wild card cutoff divider: insert after the Top-1 wild-card-qualified team
      if (!wcCutoffInserted) {
        if (s.wild_card_qualified) wcTeamsShown++;
        if (wcTeamsShown >= 1 && i < standings.length - 1 && !standings[i + 1].wild_card_qualified && !wcCutoffInserted) {
          rows += '<tr class="res-wc-divider"><td colspan="10"><span class="res-wc-divider-label">\u2015 Top-1 Wild-Card Cutoff \u2015</span></td></tr>';
          wcCutoffInserted = true;
        }
      }

      var rankClass = rank <= 3 ? 'rank-' + rank : '';
      var color = s.accent_color || '#F97316';
      var statusHtml = '<span class="res-status ' + (s.status || 'ACTIVE') + '">' + (s.status || 'ACTIVE').replace(/_/g, ' ') + '</span>';
      if (isLive) statusHtml += ' <span class="res-status" style="background:rgba(239,68,68,0.15);color:#EF4444;border-color:rgba(239,68,68,0.4);margin-left:3px;">LIVE</span>';
      var membersList = Array.isArray(s.members) ? s.members.filter(Boolean) : [];
      var speakerText = (s.designated_speaker || '') + (membersList.length === 1 && s.designated_speaker ? ' (Solo)' : '');

      rows += '<tr class="' + rowClass + '" data-team-id="' + escHTML(s.team_id) + '" onclick="toggleHistory(this)">';
      rows += '<td class="res-rank-cell ' + rankClass + '">' + rank + '</td>';
      rows += '<td><div class="res-team-cell">';
      rows += '<div class="res-team-swatch" style="background:' + escHTML(color) + '"></div>';
      rows += '<div><div class="res-team-name">' + escHTML(s.name || s.team_id) + '</div>';
      rows += '<div class="res-team-speaker">' + escHTML(speakerText) + '</div></div>';
      rows += '</div></td>';
      rows += '<td>' + statusHtml + '</td>';
      rows += '<td class="td-num">' + (s.matches_played || 0) + '</td>';
      rows += '<td class="td-num" style="color:var(--emerald)">' + (s.wins || 0) + '</td>';
      rows += '<td class="td-num" style="color:var(--crimson)">' + (s.losses || 0) + '</td>';
      rows += '<td class="td-num">' + (s.rapid_fire_points || 0) + '</td>';
      rows += '<td class="td-num">' + (s.buzzer_points || 0) + '</td>';
      rows += '<td class="td-num" style="color:var(--crimson)">' + (s.foul_penalties || 0) + '</td>';
      rows += '<td class="td-total">' + (s.total_score || 0) + '</td>';
      rows += '</tr>';

      // History expand row
      if (expandedTeamId === s.team_id) {
        rows += '<tr class="res-history-row"><td colspan="10">';
        rows += buildHistoryHTML(s);
        rows += '</td></tr>';
      }
    }

    tbody.innerHTML = rows;
  }

  function buildHistoryHTML(s) {
    var history = s.match_history || [];
    var html = '<div class="res-history-inner">';
    html += '<h4>' + escHTML(s.name) + ' &#8212; Match History</h4>';
    if (!history.length) {
      html += '<p style="color:var(--text-muted);font-size:11px;">No matches played yet.</p>';
    } else {
      html += '<table class="res-history-table"><thead><tr>';
      html += '<th>M#</th><th>Stage</th><th>Opponent</th><th>Score</th><th>RF</th><th>BZ</th><th>Fouls</th><th>Result</th>';
      html += '</tr></thead><tbody>';
      for (var i = 0; i < history.length; i++) {
        var h = history[i];
        var outcome = (h.outcome || 'PENDING').toUpperCase();
        var outcomeClass = outcome === 'WIN' ? 'win' : (outcome === 'LOSS' ? 'loss' : '');
        var mn = String(h.match_number || '?').padStart(2, '0');
        html += '<tr>';
        html += '<td>M' + mn + '</td>';
        html += '<td>' + escHTML((h.stage || '').replace(/_/g, ' ')) + '</td>';
        html += '<td>' + escHTML(h.opponent_name || h.opponent_id || '--') + '</td>';
        html += '<td><strong>' + (h.team_score || 0) + '</strong> – ' + (h.opponent_score || 0) + '</td>';
        html += '<td>' + (h.rapid_fire_points || 0) + '</td>';
        html += '<td>' + (h.buzzer_points || 0) + '</td>';
        html += '<td>' + (h.foul_penalties || 0) + '</td>';
        html += '<td class="' + outcomeClass + '">' + outcome + '</td>';
        html += '</tr>';
      }
      html += '</tbody></table>';
    }
    html += '</div>';
    return html;
  }

  /* toggle exposed to onclick attr */
  window.toggleHistory = function (rowEl) {
    var teamId = rowEl.getAttribute('data-team-id');
    if (expandedTeamId === teamId) {
      expandedTeamId = null;
    } else {
      expandedTeamId = teamId;
    }
    // Re-render leaderboard section only
    var progress = (latestState && latestState.tournament_progress) || {};
    renderLeaderboard(progress.standings || [], latestState);
  };

  /* ---- Mini Bracket ---- */
  function renderBracket(progress) {
    var bracketEl = el('bracketMini');
    if (!bracketEl) return;
    var completed = progress.completed_results || [];
    var allMatches = getAllMatchSlots(progress);
    var html = '';
    var stages = [
      { label: 'Qualifiers', nums: [1,2,3,4,5,6,7] },
      { label: 'Quarterfinals', nums: [8,9,10,11] },
      { label: 'Semifinals', nums: [12,13] },
      { label: 'Grand Final', nums: [14] },
    ];
    for (var si = 0; si < stages.length; si++) {
      var stg = stages[si];
      html += '<div class="res-bracket-stage-label">' + stg.label + '</div>';
      for (var ni = 0; ni < stg.nums.length; ni++) {
        var mn = stg.nums[ni];
        var match = findMatch(allMatches, mn);
        html += renderBracketMatch(match, mn, progress);
      }
    }
    bracketEl.innerHTML = html;
  }

  function getAllMatchSlots(progress) {
    var completed = progress.completed_results || [];
    // Build a map of match_number -> data
    var map = {};
    for (var i = 0; i < completed.length; i++) {
      var m = completed[i];
      map[m.match_number] = { status: 'completed', data: m };
    }
    // Check live match
    var h = progress.highlights || {};
    if (h.live_match) {
      var lm = h.live_match;
      map[lm.match_number] = { status: 'live', data: lm };
    }
    return map;
  }

  function findMatch(map, num) {
    return map[num] || null;
  }

  function renderBracketMatch(match, num, progress) {
    var mnStr = 'M' + String(num).padStart(2, '0');
    if (!match) {
      // Pending / unknown
      return '<div class="res-bracket-match pending">' +
        '<span class="res-bracket-match-num">' + mnStr + '</span>' +
        '<div class="res-bracket-match-teams">' +
        '<div class="res-bracket-team">TBD</div><div class="res-bracket-team">TBD</div>' +
        '</div></div>';
    }
    var d = match.data;
    var statusClass = match.status;
    var taName = d.team_a_name || d.team_a_id || 'TBD';
    var tbName = d.team_b_name || d.team_b_id || 'TBD';
    var taWinner = match.status === 'completed' && d.winner_id && d.team_a_id && d.winner_id === d.team_a_id;
    var tbWinner = match.status === 'completed' && d.winner_id && d.team_b_id && d.winner_id === d.team_b_id;
    var scoreStr = '';
    if (match.status === 'completed') {
      scoreStr = (d.score_a || 0) + '–' + (d.score_b || 0);
    } else if (match.status === 'live') {
      scoreStr = (d.score_a || 0) + '–' + (d.score_b || 0);
    }
    return '<div class="res-bracket-match ' + statusClass + '">' +
      '<span class="res-bracket-match-num">' + mnStr + '</span>' +
      '<div class="res-bracket-match-teams">' +
      '<div class="res-bracket-team' + (taWinner ? ' winner' : '') + '">' + escHTML(taName) + '</div>' +
      '<div class="res-bracket-team' + (tbWinner ? ' winner' : '') + '">' + escHTML(tbName) + '</div>' +
      '</div>' +
      (scoreStr ? '<div class="res-bracket-match-score">' + escHTML(scoreStr) + '</div>' : '') +
      '</div>';
  }

  /* ---- Match Results List ---- */
  function renderMatchResults(progress) {
    var listEl = el('matchResultsList');
    if (!listEl) return;
    var completed = progress.completed_results || [];
    var h = progress.highlights || {};
    var liveMn = h.live_match ? h.live_match.match_number : null;
    var html = '';
    for (var num = 1; num <= 14; num++) {
      var cr = null;
      for (var ci = 0; ci < completed.length; ci++) {
        if (completed[ci].match_number === num) { cr = completed[ci]; break; }
      }
      var isLive = (liveMn === num);
      if (cr) {
        // Completed
        var taW = cr.winner_id && cr.winner_id === cr.team_a_id;
        var tbW = cr.winner_id && cr.winner_id === cr.team_b_id;
        html += '<div class="res-match-card mc-completed">';
        html += '<div class="res-mc-num">M' + String(num).padStart(2, '0') + '</div>';
        html += '<div class="res-mc-teams">';
        html += '<div class="res-mc-team' + (taW ? ' winner' : '') + '">' + escHTML(cr.team_a_name || '') + '</div>';
        html += '<div class="res-mc-team' + (tbW ? ' winner' : '') + '">' + escHTML(cr.team_b_name || '') + '</div>';
        html += '</div>';
        html += '<div class="res-mc-score-wrap">';
        html += '<div class="res-mc-score">' + (cr.score_a || 0) + '–' + (cr.score_b || 0) + '</div>';
        html += '<div class="res-mc-stage-badge">' + escHTML((cr.stage || '').replace(/_/g, ' ')) + '</div>';
        html += '</div>';
        html += '</div>';
      } else if (isLive) {
        var lm = h.live_match;
        html += '<div class="res-match-card mc-live">';
        html += '<div class="res-mc-num">M' + String(num).padStart(2, '0') + '</div>';
        html += '<div class="res-mc-teams">';
        html += '<div class="res-mc-team">' + escHTML(lm.team_a_name || '') + '</div>';
        html += '<div class="res-mc-team">' + escHTML(lm.team_b_name || '') + '</div>';
        html += '</div>';
        html += '<div class="res-mc-score-wrap">';
        html += '<div class="res-mc-score">' + (lm.score_a || 0) + '–' + (lm.score_b || 0) + '</div>';
        html += '<div class="res-mc-live-badge"><span style="width:6px;height:6px;border-radius:50%;background:#EF4444;display:inline-block;animation:livePulse 1.2s infinite"></span> LIVE</div>';
        html += '</div>';
        html += '</div>';
      } else {
        // Pending
        html += '<div class="res-match-card mc-pending">';
        html += '<div class="res-mc-num">M' + String(num).padStart(2, '0') + '</div>';
        html += '<div class="res-mc-teams">';
        html += '<div class="res-mc-team">TBD</div>';
        html += '<div class="res-mc-team">TBD</div>';
        html += '</div>';
        html += '<div class="res-mc-score-wrap"><div class="res-mc-stage-badge">SCHEDULED</div></div>';
        html += '</div>';
      }
    }
    listEl.innerHTML = html;
  }

  /* ---- HTML escape ---- */
  function escHTML(str) {
    return String(str || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  /* ---- Boot ---- */
  connect();

})();
