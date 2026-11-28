/**
 * EEECi FA'26 — EEE Brain Battle (Module 06)
 * Tournament Admin Controller (Laptop 3)
 * 100% Offline, Server-Authoritative Real-Time WebSocket & REST Administration
 */

(function () {
  "use strict";

  // ── DOM Elements ─────────────────────────────────────────────
  var el = function (id) { return document.getElementById(id); };

  var pinGate = el("pinGate");
  var adminApp = el("adminApp");
  var pinForm = el("pinForm");
  var pinInput = el("pinInput");
  var pinError = el("pinError");
  var actionToast = el("actionToast");
  var logoutBtn = el("logoutBtn");
  var statusBanner = el("statusBanner");
  var latencyBadge = el("latencyBadge");

  // Overview Strip
  var stageDisplay = el("stageDisplay");
  var matchDisplay = el("matchDisplay");
  var phaseDisplay = el("phaseDisplay");
  var activeTeamsDisplay = el("activeTeamsDisplay");
  var championDisplay = el("championDisplay");
  var displayViewBadge = el("displayViewBadge");

  // Modules
  var teamSelect = el("teamSelect");
  var teamEditorForm = el("teamEditorForm");
  var teamNameInput = el("teamNameInput");
  var member1Input = el("member1Input");
  var member2Input = el("member2Input");
  var speakerSelect = el("speakerSelect");
  var accentInput = el("accentInput");
  var rosterList = el("rosterList");

  // Bracket & Wildcard
  var bracketLeftQual = el("bracketLeftQual");
  var bracketLeftQf = el("bracketLeftQf");
  var bracketLeftSf = el("bracketLeftSf");
  var bracketRightQual = el("bracketRightQual");
  var bracketRightQf = el("bracketRightQf");
  var bracketRightSf = el("bracketRightSf");
  var bracketFinal = el("bracketFinal");
  var stageLockToggle = el("stageLockToggle");
  var ledgerDrawer = el("ledgerDrawer");
  var ledgerBody = el("ledgerBody");
  var ledgerTitle = el("ledgerTitle");
  var ledgerClose = el("ledgerClose");
  var wildCardLeaderboard = el("wildCardLeaderboard");
  var wildCardTieBanner = el("wildCardTieBanner");
  var tieBreakerWinnerSelect = el("tieBreakerWinnerSelect");
  var btnResolveTie = el("btnResolveTie");
  var btnRepopulateQf = el("btnRepopulateQf");
  var btnSeedOfficial14 = el("btnSeedOfficial14");

  // Score Correction
  var scoreAdjustmentForm = el("scoreAdjustmentForm");
  var scoreTeamSelect = el("scoreTeamSelect");
  var currentTeamScoreDisplay = el("currentTeamScoreDisplay");
  var adjustmentMode = el("adjustmentMode");
  var scoreValueLabel = el("scoreValueLabel");
  var scoreValueInput = el("scoreValueInput");
  var scoreReasonInput = el("scoreReasonInput");

  // Audit Log & Exports
  var auditLogTbody = el("auditLogTbody");
  var btnRefreshLogs = el("btnRefreshLogs");
  var btnExportCsv = el("btnExportCsv");
  var btnExportJson = el("btnExportJson");
  var btnResetTournament = el("btnResetTournament");

  // Reset Modal
  var resetModal = el("resetModal");
  var resetConfirmInput = el("resetConfirmInput");
  var btnCancelReset = el("btnCancelReset");
  var btnConfirmReset = el("btnConfirmReset");

  // ── State Variables ──────────────────────────────────────────
  var client = null;
  var state = {};
  var adminPin = sessionStorage.getItem("admin_pin") || "2222";
  var activeLogFilter = "all";
  var toastTimeout = null;
  var auditEntries = [];
  var openLedgerTeam = "";
  var stageLockSync = false;

  // ── Toast Feedback ───────────────────────────────────────────
  function showToast(message, isError) {
    if (!actionToast) return;
    actionToast.textContent = message;
    actionToast.className = "action-toast " + (isError ? "error" : "success");
    actionToast.classList.remove("hidden");
    if (toastTimeout) clearTimeout(toastTimeout);
    toastTimeout = setTimeout(function () {
      actionToast.classList.add("hidden");
    }, 4500);
  }

  // ── Team Helpers ─────────────────────────────────────────────
  function getTeam(teamId) {
    if (!teamId || !state.teams) return null;
    return state.teams[teamId] || null;
  }

  function getTeamName(teamId) {
    var team = getTeam(teamId);
    return team ? team.name : (teamId || "--");
  }

  function getTeamColor(teamId) {
    var team = getTeam(teamId);
    return team && team.accent_color ? team.accent_color : "#f97316";
  }

  // ── Authentication Management ────────────────────────────────
  function setAuthenticated(value) {
    pinGate.classList.toggle("hidden", value);
    adminApp.classList.toggle("hidden", !value);
    if (value) {
      connectWs();
      loadAuditLogs();
    } else if (client && client.stop) {
      client.stop();
    }
  }

  function connectWs() {
    if (!window.QuizClient) {
      showToast("QuizClient library unavailable.", true);
      return;
    }
    if (client && client.stop) {
      client.stop();
    }

    client = new window.QuizClient({
      role: "admin",
      pin: adminPin,
      pinOrCode: adminPin,
      onState: updateState,
      onStatusChange: function (status, text) {
        statusBanner.textContent = status === "online" ? "CONNECTED" : (text || status).toUpperCase();
        statusBanner.className = "status " + (status === "online" ? "online" : "reconnecting");
        if (status === "auth_error") {
          sessionStorage.removeItem("admin_pin");
          setAuthenticated(false);
          pinError.textContent = "Invalid Admin PIN (2222 required).";
        }
      },
      onLatency: function (ms) {
        if (latencyBadge) {
          latencyBadge.textContent = Math.round(ms) + " ms";
          latencyBadge.className = "latency " + (ms > 80 ? "bad" : ms > 35 ? "warn" : "good");
        }
      },
      onAck: function (ack) {
        var actionName = ack.action ? ack.action.replace(/_/g, " ") : "Action";
        showToast(actionName.toUpperCase() + " applied successfully.", false);
        loadAuditLogs();
      },
      onError: function (err) {
        showToast(err.message || "Action rejected by server.", true);
      }
    });

    client.init();
  }

  function send(action, payload, reason) {
    if (!client || !client.sendAction) {
      showToast("Admin console not connected yet.", true);
      return false;
    }
    var ok = client.sendAction(action, payload || {}, reason || "Admin console action");
    if (!ok) {
      showToast("Unable to send action while disconnected.", true);
    }
    return ok;
  }

  // ── State Renderer ───────────────────────────────────────────
  function updateState(nextState) {
    state = nextState || {};

    var ev = state.event || {};
    var match = state.current_match || {};
    var round = state.round || {};
    var bracket = ev.bracket || {};

    // 1. Overview Bar
    if (stageDisplay) stageDisplay.textContent = String(round.stage || ev.stage || "QUALIFIER").toUpperCase();
    if (matchDisplay) {
      var mNum = match.match_number || ev.match_number || 1;
      var totalMatches = (bracket.matches && bracket.matches.length) || 14;
      matchDisplay.textContent = "M" + String(mNum).padStart(2, "0") + " / " + totalMatches;
    }
    if (phaseDisplay) phaseDisplay.textContent = String(round.phase || "IDLE").replace(/_/g, " ").toUpperCase();
    if (activeTeamsDisplay) {
      var tA = getTeamName(match.team_a_id);
      var tB = getTeamName(match.team_b_id);
      activeTeamsDisplay.textContent = tA + " vs " + tB;
    }
    if (championDisplay) {
      championDisplay.textContent = bracket.champion ? getTeamName(bracket.champion).toUpperCase() : "UNDECIDED";
    }
    if (displayViewBadge) {
      displayViewBadge.textContent = String(state.display_view || "AUTO").toUpperCase();
    }

    // Update active highlight on Display View buttons
    document.querySelectorAll("[data-display-view]").forEach(function (btn) {
      var v = btn.dataset.displayView;
      var active = (state.display_view || "auto") === v;
      btn.classList.toggle("active-view", active);
    });

    syncStageLock(readStageLocked(state));

    // 2. Roster Management
    renderRosterSection();
    if (openLedgerTeam) renderLedger();

    // 3. Bracket & Wild-Cards
    renderBracket(bracket.matches || []);
    renderWildCards(bracket);

    // 4. Update Score Form
    updateScoreFormCurrent();
  }

  // ── Roster Module ────────────────────────────────────────────
  function populateTeamSelectors() {
    var teams = Object.values(state.teams || {});
    var selectedEditTeam = teamSelect.value;
    var selectedScoreTeam = scoreTeamSelect.value;

    teamSelect.innerHTML = teams.map(function (t) {
      return '<option value="' + t.id + '">' + t.name + ' (' + t.id + ')</option>';
    }).join("");

    if (selectedEditTeam && state.teams[selectedEditTeam]) {
      teamSelect.value = selectedEditTeam;
    }

    // Score Team dropdown: prioritize live match teams at top
    var currentMatch = state.current_match || {};
    var liveA = currentMatch.team_a_id;
    var liveB = currentMatch.team_b_id;

    var scoreOptions = [];
    if (liveA && state.teams[liveA]) {
      scoreOptions.push('<option value="' + liveA + '">🔴 LIVE A: ' + getTeamName(liveA) + '</option>');
    }
    if (liveB && state.teams[liveB]) {
      scoreOptions.push('<option value="' + liveB + '">🔵 LIVE B: ' + getTeamName(liveB) + '</option>');
    }
    teams.forEach(function (t) {
      if (t.id !== liveA && t.id !== liveB) {
        scoreOptions.push('<option value="' + t.id + '">' + t.name + ' (' + t.id + ')</option>');
      }
    });
    scoreTeamSelect.innerHTML = scoreOptions.join("");
    if (selectedScoreTeam) {
      scoreTeamSelect.value = selectedScoreTeam;
    }
  }

  function loadTeamToEditor(teamId) {
    var team = getTeam(teamId);
    if (!team) return;

    teamNameInput.value = team.name || "";
    member1Input.value = (team.members && team.members[0]) || "";
    member2Input.value = (team.members && team.members[1]) || "";
    accentInput.value = team.accent_color || "#0ea5e9";

    updateSpeakerOptions(team.designated_speaker);
  }

  function updateSpeakerOptions(designatedSpeaker) {
    var m1 = (member1Input.value || "").trim();
    var m2 = (member2Input.value || "").trim();
    var options = [];

    if (m1) options.push('<option value="' + m1 + '">' + m1 + '</option>');
    if (m2) options.push('<option value="' + m2 + '">' + m2 + '</option>');
    if (!options.length) options.push('<option value="">-- No members entered --</option>');

    speakerSelect.innerHTML = options.join("");
    if (designatedSpeaker && (designatedSpeaker === m1 || designatedSpeaker === m2)) {
      speakerSelect.value = designatedSpeaker;
    } else if (m1) {
      speakerSelect.value = m1;
    }
  }

  function renderRosterSection() {
    populateTeamSelectors();
    var currentSelected = teamSelect.value;
    if (currentSelected && state.teams[currentSelected]) {
      loadTeamToEditor(currentSelected);
    }

    var teams = Object.values(state.teams || {});
    rosterList.innerHTML = teams.map(function (t) {
      var color = t.accent_color || "#0ea5e9";
      var cleanMembers = (t.members || []).filter(function (m) { return m != null && String(m).trim() !== ""; });
      var mStr = cleanMembers.length === 1
        ? esc(cleanMembers[0]) + " (Solo)"
        : (esc(cleanMembers.join(" & ")) || "No members");
      var wins = (t.win_loss && t.win_loss.wins) || 0;
      var losses = (t.win_loss && t.win_loss.losses) || 0;

      return '<button type="button" class="roster-card roster-card-btn" data-ledger="' + esc(t.id) + '" style="border-left: 4px solid ' + esc(color) + ';">' +
        '<div class="roster-card-top">' +
          '<strong class="roster-name" style="color: ' + esc(color) + ';">' + esc(t.name) + '</strong>' +
          '<span class="roster-record">' + wins + 'W - ' + losses + 'L</span>' +
        '</div>' +
        '<p class="roster-members">👥 ' + mStr + '</p>' +
        '<p class="roster-speaker">🎙 Speaker: <b>' + esc(t.designated_speaker || "--") + '</b></p>' +
        '<p class="roster-score">Cumulative <b>' + cumulativeScore(t) + '</b></p>' +
        '<span class="roster-ledger-link">Open Match &amp; Score Audit Ledger</span>' +
      '</button>';
    }).join("");
  }

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (char) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char];
    });
  }

  function readStageLocked(snapshot) {
    if (!snapshot) return false;
    if (typeof snapshot.stage_locked === "boolean") return snapshot.stage_locked;
    if (snapshot.stage_lock && typeof snapshot.stage_lock.locked === "boolean") return snapshot.stage_lock.locked;
    if (snapshot.event && typeof snapshot.event.stage_locked === "boolean") return snapshot.event.stage_locked;
    return false;
  }

  function syncStageLock(locked) {
    if (!stageLockToggle) return;
    stageLockSync = true;
    stageLockToggle.checked = Boolean(locked);
    stageLockSync = false;
  }

  function cumulativeScore(team) {
    if (!team) return 0;
    if (team.cumulative_score != null && team.cumulative_score !== "") return Number(team.cumulative_score) || 0;
    if (team.total_score != null && team.total_score !== "") return Number(team.total_score) || 0;
    var history = Array.isArray(team.match_history) ? team.match_history : [];
    if (history.length) {
      return history.reduce(function (sum, row) {
        var value = row && (row.score != null ? row.score : row.points);
        return sum + (Number(value) || 0);
      }, 0);
    }
    var live = state.current_match && state.current_match.scores ? state.current_match.scores[team.id] : null;
    return live != null ? Number(live) || 0 : 0;
  }

  function teamHistory(team) {
    if (team && Array.isArray(team.match_history) && team.match_history.length) return team.match_history;
    var matches = ((state.event && state.event.bracket && state.event.bracket.matches) || []);
    return matches.filter(function (match) {
      return match.team_a_id === team.id || match.team_b_id === team.id;
    }).map(function (match) {
      var opponent = match.team_a_id === team.id ? match.team_b_id : match.team_a_id;
      var score = match.scores ? match.scores[team.id] : null;
      var result = !match.winner_id ? match.status || "PENDING" : (match.winner_id === team.id ? "WIN" : "LOSS");
      return {
        match_number: match.match_number,
        stage: match.stage,
        opponent: getTeamName(opponent),
        score: score == null ? "--" : score,
        result: result
      };
    });
  }

  function openLedger(teamId) {
    openLedgerTeam = teamId;
    if (ledgerDrawer) {
      ledgerDrawer.classList.remove("hidden");
      ledgerDrawer.setAttribute("aria-hidden", "false");
    }
    renderLedger();
  }

  function closeLedger() {
    openLedgerTeam = "";
    if (ledgerDrawer) {
      ledgerDrawer.classList.add("hidden");
      ledgerDrawer.setAttribute("aria-hidden", "true");
    }
  }

  function renderLedger() {
    var team = getTeam(openLedgerTeam);
    if (!ledgerBody || !team) return;
    if (ledgerTitle) ledgerTitle.textContent = team.name + " Ledger";
    var history = teamHistory(team);
    var audits = auditEntries.filter(function (entry) {
      var details = entry.details || {};
      return details.team_id === team.id || details.winner === team.id || details.loser === team.id;
    });
    var historyHtml = history.length ? history.map(function (row) {
      return "<tr><td>M" + String(row.match_number || "--").padStart(2, "0") + "</td><td>" +
        esc(row.stage || "") + "</td><td>" + esc(row.opponent || row.opponent_name || "--") +
        "</td><td class=\"font-mono\">" + esc(row.score) + "</td><td>" + esc(row.result || row.outcome || "--") + "</td></tr>";
    }).join("") : '<tr><td colspan="5" class="text-muted">No match history yet.</td></tr>';
    var auditHtml = audits.length ? audits.slice().reverse().slice(0, 40).map(function (entry) {
      var details = entry.details || {};
      var points = details.delta != null ? details.delta : (details.points_added != null ? details.points_added : "--");
      return "<tr><td class=\"font-mono\">" + esc((entry.timestamp || "").replace("T", " ").slice(0, 19)) +
        "</td><td>" + esc(entry.action || "--") + "</td><td class=\"font-mono\">" + esc(points) +
        "</td><td>" + esc(entry.reason || details.reason || "--") + "</td></tr>";
    }).join("") : '<tr><td colspan="4" class="text-muted">No audited entries for this team.</td></tr>';

    ledgerBody.innerHTML =
      '<p class="ledger-meta">Speaker <b>' + esc(team.designated_speaker || "--") + '</b> · Accent <b style="color:' + esc(team.accent_color || "#f97316") + '">' + esc(team.accent_color || "--") + '</b> · Cumulative <b>' + cumulativeScore(team) + '</b></p>' +
      '<h3>Match History</h3>' +
      '<table class="audit-table"><thead><tr><th>Match</th><th>Stage</th><th>Opponent</th><th>Score</th><th>Result</th></tr></thead><tbody>' + historyHtml + '</tbody></table>' +
      '<h3>Audit Entries</h3>' +
      '<table class="audit-table"><thead><tr><th>Time</th><th>Action</th><th>Points</th><th>Reason</th></tr></thead><tbody>' + auditHtml + '</tbody></table>' +
      '<form id="ledgerOverrideForm" class="ledger-form">' +
        '<h3>Audited Score Override</h3>' +
        '<label class="form-label">New recorded score<input id="ledgerScoreInput" class="form-input" type="number" value="' + cumulativeScore(team) + '" required></label>' +
        '<label class="form-label">Mandatory reason<input id="ledgerReasonInput" class="form-input" required placeholder="Official audited reason"></label>' +
        '<button class="btn btn-danger" type="submit">Apply Audited Override</button>' +
      '</form>';

    var form = el("ledgerOverrideForm");
    if (form) {
      form.addEventListener("submit", function (event) {
        event.preventDefault();
        var reason = (el("ledgerReasonInput").value || "").trim();
        var next = Number(el("ledgerScoreInput").value);
        if (!reason || !Number.isFinite(next)) {
          showToast("A reason and numeric score are required.", true);
          return;
        }
        var delta = next - cumulativeScore(team);
        send("admin_adjust_score", { team_id: team.id, delta: delta, score: next }, reason);
      });
    }
  }

  // ── Bracket & Wildcards Module ───────────────────────────────
  function renderBracket(matches) {
    if (!matches || !matches.length) return;

    var currentMatchNum = (state.current_match && state.current_match.match_number) || 1;

    function renderMatchCard(m) {
      var mNum = m.match_number;
      var isLive = mNum === currentMatchNum && m.status !== "COMPLETED";
      var isCompleted = m.status === "COMPLETED";
      var tA = getTeam(m.team_a_id);
      var tB = getTeam(m.team_b_id);
      var nameA = tA ? tA.name : (m.team_a_id ? m.team_a_id : "TBD");
      var nameB = tB ? tB.name : (m.team_b_id ? m.team_b_id : "TBD");
      var scoreA = (m.scores && m.scores[m.team_a_id]) != null ? m.scores[m.team_a_id] : "--";
      var scoreB = (m.scores && m.scores[m.team_b_id]) != null ? m.scores[m.team_b_id] : "--";
      var colorA = tA ? tA.accent_color : "#64748b";
      var colorB = tB ? tB.accent_color : "#64748b";

      var statusBadge = isLive ? '<span class="status-live">LIVE</span>' :
                        isCompleted ? '<span class="status-done">DONE</span>' :
                        '<span class="status-sched">SCHEDULED</span>';

      var cardClass = "bracket-match-card" + (isLive ? " match-live" : "") + (isCompleted ? " match-done" : "");

      var winnerNotice = "";
      if (m.winner_id) {
        winnerNotice = '<div class="match-winner">🏆 Winner: ' + getTeamName(m.winner_id) + '</div>';
      }

      var actionBtn = "";
      if (m.team_a_id && m.team_b_id && !isCompleted) {
        if (!isLive) {
          actionBtn = '<div style="display:flex;flex-direction:column;gap:4px;">' +
            '<button type="button" class="btn btn-sm btn-outline btn-full load-match-btn" data-load-match="' + mNum + '">Load into Live Stage</button>' +
            '<button type="button" class="btn btn-sm btn-warning btn-full advance-match-btn" data-advance-match="' + mNum + '">Advance Winner</button>' +
            '</div>';
        } else {
          actionBtn = '<button type="button" class="btn btn-sm btn-warning btn-full advance-match-btn" data-advance-match="' + mNum + '">Advance Winner</button>';
        }
      }

      return '<div class="' + cardClass + '">' +
        '<div class="match-card-header">' +
          '<span class="match-num">M' + String(mNum).padStart(2, "0") + ' • ' + m.stage + '</span>' +
          statusBadge +
        '</div>' +
        '<div class="match-team-row ' + (m.winner_id && m.winner_id === m.team_a_id ? "row-winner" : "") + '">' +
          '<span class="team-dot" style="background: ' + colorA + ';"></span>' +
          '<span class="team-label">' + nameA + '</span>' +
          '<strong class="team-pts">' + scoreA + '</strong>' +
        '</div>' +
        '<div class="match-team-row ' + (m.winner_id && m.winner_id === m.team_b_id ? "row-winner" : "") + '">' +
          '<span class="team-dot" style="background: ' + colorB + ';"></span>' +
          '<span class="team-label">' + nameB + '</span>' +
          '<strong class="team-pts">' + scoreB + '</strong>' +
        '</div>' +
        winnerNotice +
        actionBtn +
      '</div>';
    }

    if (bracketLeftQual) {
      bracketLeftQual.innerHTML = matches.filter(function (m) { return m.match_number >= 1 && m.match_number <= 4; }).map(renderMatchCard).join("");
    }
    if (bracketLeftQf) {
      bracketLeftQf.innerHTML = matches.filter(function (m) { return m.match_number >= 8 && m.match_number <= 9; }).map(renderMatchCard).join("");
    }
    if (bracketLeftSf) {
      bracketLeftSf.innerHTML = matches.filter(function (m) { return m.match_number === 12; }).map(renderMatchCard).join("");
    }
    if (bracketRightQual) {
      bracketRightQual.innerHTML = matches.filter(function (m) { return m.match_number >= 5 && m.match_number <= 7; }).map(renderMatchCard).join("");
    }
    if (bracketRightQf) {
      bracketRightQf.innerHTML = matches.filter(function (m) { return m.match_number >= 10 && m.match_number <= 11; }).map(renderMatchCard).join("");
    }
    if (bracketRightSf) {
      bracketRightSf.innerHTML = matches.filter(function (m) { return m.match_number === 13; }).map(renderMatchCard).join("");
    }
    if (bracketFinal) {
      bracketFinal.innerHTML = matches.filter(function (m) { return m.match_number === 14; }).map(renderMatchCard).join("");
    }

    // Attach load match listener
    document.querySelectorAll("[data-load-match]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var num = Number(btn.dataset.loadMatch);
        var m = matches.find(function (item) { return item.match_number === num; });
        if (!m || !m.team_a_id || !m.team_b_id) {
          showToast("Match teams are not yet determined.", true);
          return;
        }
        send("setup_match", {
          stage: m.stage,
          match_number: m.match_number,
          team_a_id: m.team_a_id,
          team_b_id: m.team_b_id
        }, "Admin loaded match M" + num);
      });
    });

    // Attach advance match listener
    document.querySelectorAll("[data-advance-match]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var mNum = Number(btn.dataset.advanceMatch);
        var winnerId = btn.dataset.winnerId || null;
        if (!window.confirm("Advance the winner of M" + String(mNum).padStart(2, "0") + " to the next round?")) return;
        var payload = { match_number: mNum };
        if (winnerId) payload.winner_id = winnerId;
        send("advance_winner", payload, "Admin advanced winner for M" + mNum);
      });
    });
  }

  function renderWildCards(bracket) {
    if (!wildCardLeaderboard) return;

    var matches = bracket.matches || [];
    var qualMatches = matches.filter(function (m) { return m.match_number >= 1 && m.match_number <= 7; });
    var losers = [];

    qualMatches.forEach(function (m) {
      if (m.loser_id) {
        var score = (m.scores && m.scores[m.loser_id]) != null ? m.scores[m.loser_id] : 0;
        losers.push({
          teamId: m.loser_id,
          score: score,
          matchNum: m.match_number
        });
      }
    });

    losers.sort(function (a, b) { return b.score - a.score; });

    var top1 = (bracket.wild_cards || []).slice(0, 1);
    var tiedTeams = bracket.wild_card_tied_teams || [];

    // Check if tie exists
    if (tiedTeams.length > 0) {
      wildCardTieBanner.classList.remove("hidden");
      tieBreakerWinnerSelect.innerHTML = tiedTeams.map(function (tid) {
        return '<option value="' + tid + '">' + getTeamName(tid) + '</option>';
      }).join("");
    } else {
      wildCardTieBanner.classList.add("hidden");
    }

    if (!losers.length) {
      wildCardLeaderboard.innerHTML = '<p class="text-muted text-center" style="padding: 1rem;">No Qualifier matches completed yet. Wild-card rankings will appear here as Qualifier losers are determined.</p>';
      return;
    }

    wildCardLeaderboard.innerHTML = '<table class="wildcard-table">' +
      '<thead>' +
        '<tr>' +
          '<th>Rank</th>' +
          '<th>Team</th>' +
          '<th>Qualifier Match</th>' +
          '<th>Score</th>' +
          '<th>Wild-Card Status</th>' +
        '</tr>' +
      '</thead>' +
      '<tbody>' +
        losers.map(function (item, idx) {
          var isTop1 = top1.includes(item.teamId) || (top1.length === 0 && idx === 0 && !tiedTeams.length);
          var isTied = tiedTeams.includes(item.teamId);
          var statusPill = isTop1 ? '<span class="wc-pill wc-advance">ADVANCING TO QF</span>' :
                           isTied ? '<span class="wc-pill wc-tied">TIEBREAKER PENDING</span>' :
                           '<span class="wc-pill wc-elim">ELIMINATED</span>';

          return '<tr class="' + (isTop1 ? "row-advancing" : isTied ? "row-tied" : "") + '">' +
            '<td>#' + (idx + 1) + '</td>' +
            '<td><strong style="color: ' + getTeamColor(item.teamId) + ';">' + getTeamName(item.teamId) + '</strong></td>' +
            '<td>Match ' + item.matchNum + '</td>' +
            '<td class="font-mono"><b>' + item.score + ' pts</b></td>' +
            '<td>' + statusPill + '</td>' +
          '</tr>';
        }).join("") +
      '</tbody>' +
    '</table>';
  }

  // ── Score Adjustment Form Helpers ────────────────────────────
  function updateScoreFormCurrent() {
    var teamId = scoreTeamSelect.value;
    var team = getTeam(teamId);
    if (!team) {
      currentTeamScoreDisplay.textContent = "0";
      return;
    }
    var currentMatch = state.current_match;
    var liveScore = currentMatch && currentMatch.scores ? currentMatch.scores[teamId] : null;
    currentTeamScoreDisplay.textContent = liveScore != null ? liveScore : "0";
  }

  // ── Audit Logs Module ────────────────────────────────────────
  async function loadAuditLogs() {
    try {
      var res = await fetch("/api/admin/logs?limit=150", { credentials: "same-origin" });
      if (!res.ok) return;
      var data = await res.json();
      renderAuditLogs(data.logs || []);
    } catch (err) {
      // ignore
    }
  }

  function renderAuditLogs(entries) {
    if (!auditLogTbody) return;
    if (!entries || !entries.length) {
      auditLogTbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted">No audit entries recorded yet.</td></tr>';
      return;
    }

    var filtered = entries.filter(function (entry) {
      var act = entry.action || "";
      if (activeLogFilter === "score") {
        return ["admin_adjust_score", "mark_correct", "mark_wrong", "foul_penalty"].includes(act);
      }
      if (activeLogFilter === "fouls") {
        return ["warning_logged", "foul_penalty"].includes(act);
      }
      if (activeLogFilter === "bracket") {
        return ["setup_match", "end_match", "advance_winner", "resolve_wild_card_tie", "override_quarterfinal_pairings", "init_default_tournament", "seed_official_14_teams"].includes(act);
      }
      if (activeLogFilter === "undo") {
        return act === "undo_last_action";
      }
      return true;
    });

    filtered.reverse();

    auditLogTbody.innerHTML = filtered.slice(0, 100).map(function (entry) {
      var ts = entry.timestamp ? entry.timestamp.split("T")[1]?.slice(0, 8) || entry.timestamp : "--";
      var act = entry.action ? entry.action.replace(/_/g, " ") : "--";
      var det = entry.details || {};
      var target = det.team_id ? getTeamName(det.team_id) : (det.winner ? getTeamName(det.winner) : "--");
      var points = det.delta != null ? (det.delta > 0 ? "+" + det.delta : det.delta) :
                   det.points_added != null ? "+" + det.points_added :
                   det.new_score != null ? "New: " + det.new_score : "--";
      var reason = entry.reason || det.reason || "--";

      return '<tr>' +
        '<td class="font-mono text-muted">' + ts + '</td>' +
        '<td><b>' + act.toUpperCase() + '</b></td>' +
        '<td>' + target + '</td>' +
        '<td class="font-mono">' + points + '</td>' +
        '<td>' + reason + '</td>' +
      '</tr>';
    }).join("");
  }

  // ── Event Listeners ──────────────────────────────────────────

  // PIN Gate Form Submit
  pinForm.addEventListener("submit", async function (event) {
    event.preventDefault();
    var enteredPin = (pinInput.value || "").trim();
    if (!enteredPin) return;

    try {
      var res = await fetch("/api/admin/auth", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pin: enteredPin })
      });
      if (!res.ok) throw new Error("Invalid Admin PIN");
      adminPin = enteredPin;
      sessionStorage.setItem("admin_pin", adminPin);
      pinError.textContent = "";
      setAuthenticated(true);
    } catch (err) {
      pinError.textContent = err.message;
    }
  });

  // Logout Button
  logoutBtn.addEventListener("click", function () {
    sessionStorage.removeItem("admin_pin");
    document.cookie = "admin_session=; Max-Age=0; path=/;";
    adminPin = "";
    setAuthenticated(false);
  });

  // Display Controller Buttons
  document.querySelectorAll("[data-display-view]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var view = btn.dataset.displayView;
      send("set_display_view", { view: view }, "Admin projector override to " + view);
    });
  });

  // Team Selector Change
  teamSelect.addEventListener("change", function () {
    loadTeamToEditor(teamSelect.value);
  });

  if (rosterList) {
    rosterList.addEventListener("click", function (event) {
      var ledgerBtn = event.target.closest("[data-ledger]");
      if (ledgerBtn) openLedger(ledgerBtn.dataset.ledger);
    });
  }
  if (ledgerClose) ledgerClose.addEventListener("click", closeLedger);

  member1Input.addEventListener("input", function () { updateSpeakerOptions(speakerSelect.value); });
  member2Input.addEventListener("input", function () { updateSpeakerOptions(speakerSelect.value); });

  // Color Swatches
  document.querySelectorAll(".color-pill").forEach(function (pill) {
    pill.addEventListener("click", function () {
      accentInput.value = pill.dataset.color;
    });
  });

  // Team Editor Form Submit
  teamEditorForm.addEventListener("submit", function (event) {
    event.preventDefault();
    var tid = teamSelect.value;
    var name = teamNameInput.value.trim();
    var m1 = member1Input.value.trim();
    var m2 = member2Input.value.trim();
    var speaker = speakerSelect.value.trim();
    var color = accentInput.value;

    var members = [m1, m2].filter(Boolean);
    if (!members.length) {
      showToast("At least Member 1 is required.", true);
      return;
    }

    // Check if matches are underway
    var bracket = (state.event && state.event.bracket) || {};
    var matches = bracket.matches || [];
    var underway = matches.some(function (m) { return m.status === "IN_PROGRESS" || m.status === "COMPLETED"; });
    if (underway) {
      if (!window.confirm("RULEBOOK WARNING: Tournament matches have already begun. Are you sure you have tournament director approval to update this team roster?")) {
        return;
      }
    }

    send("admin_update_team", {
      team_id: tid,
      name: name,
      members: members,
      designated_speaker: speaker,
      accent_color: color
    }, "Admin updated team " + tid);
  });

  // Score Team Select Change
  scoreTeamSelect.addEventListener("change", updateScoreFormCurrent);

  // Score Adjustment Mode Toggle
  adjustmentMode.addEventListener("change", function () {
    if (adjustmentMode.value === "set") {
      scoreValueLabel.textContent = "Exact Score Value";
    } else {
      scoreValueLabel.textContent = "Point Delta (+/-)";
    }
  });

  // Score Preset Buttons
  document.querySelectorAll(".btn-preset").forEach(function (btn) {
    btn.addEventListener("click", function () {
      scoreReasonInput.value = btn.dataset.reason;
    });
  });

  // Score Adjustment Form Submit
  scoreAdjustmentForm.addEventListener("submit", function (event) {
    event.preventDefault();
    var tid = scoreTeamSelect.value;
    var reason = scoreReasonInput.value.trim();
    var num = Number(scoreValueInput.value);

    if (!reason) {
      showToast("A mandatory reason is required to adjust scores.", true);
      scoreReasonInput.focus();
      return;
    }

    var delta = num;
    if (adjustmentMode.value === "set") {
      var currentMatch = state.current_match;
      var cur = (currentMatch && currentMatch.scores && currentMatch.scores[tid]) || 0;
      delta = num - cur;
    }

    send("admin_adjust_score", {
      team_id: tid,
      delta: delta
    }, reason);

    scoreReasonInput.value = "";
  });

  // Wild Card Tie Resolver Button
  btnResolveTie.addEventListener("click", function () {
    var winner = tieBreakerWinnerSelect.value;
    if (!winner) return;
    if (!window.confirm("Confirm Team " + getTeamName(winner) + " as the wild-card tiebreaker winner?")) return;
    send("resolve_wild_card_tie", { winning_team_id: winner }, "Admin resolved wild card tie");
  });

  // Seed Official 14 Teams Button
  if (btnSeedOfficial14) {
    btnSeedOfficial14.addEventListener("click", function () {
      if (!window.confirm("Seed all 14 official EEECi FA'26 teams (T01–T14) and reset the bracket to M1–M14?")) return;
      send("seed_official_14_teams", {}, "Admin seeded official 14 teams");
    });
  }

  // Populate Quarterfinals Button (7 Winners + Top-1 Wild-Card)
  btnRepopulateQf.addEventListener("click", function () {
    var bracket = (state.event && state.event.bracket) || {};
    var winners = bracket.qualifier_winners || [];
    var wildCards = bracket.wild_cards || [];

    if (winners.length < 7 || wildCards.length < 1) {
      if (!window.confirm("Not all 7 Qualifiers and Top-1 Wild-Card have completed. Attempt quarterfinal population anyway?")) {
        return;
      }
    }

    var pairings = [
      { match_number: 8,  team_a_id: winners[0] || "T01", team_b_id: wildCards[0] || "T02" },
      { match_number: 9,  team_a_id: winners[1] || "T03", team_b_id: winners[2] || "T05" },
      { match_number: 10, team_a_id: winners[3] || "T07", team_b_id: winners[4] || "T09" },
      { match_number: 11, team_a_id: winners[5] || "T11", team_b_id: winners[6] || "T13" }
    ];

    send("override_quarterfinal_pairings", { pairings: pairings }, "Admin populated quarterfinal pairings");
  });

  // Audit Log Filter Buttons
  document.querySelectorAll(".btn-filter").forEach(function (btn) {
    btn.addEventListener("click", function () {
      document.querySelectorAll(".btn-filter").forEach(function (b) { b.classList.remove("active"); });
      btn.classList.add("active");
      activeLogFilter = btn.dataset.filter;
      loadAuditLogs();
    });
  });

  if (stageLockToggle) {
    stageLockToggle.addEventListener("change", function () {
      if (stageLockSync) return;
      var locked = stageLockToggle.checked;
      send("toggle_stage_lock", { stage_locked: locked }, "Stage lock set to " + locked);
    });
  }

  btnRefreshLogs.addEventListener("click", loadAuditLogs);

  // Report Downloads
  btnExportCsv.addEventListener("click", function () {
    window.open("/api/admin/report?format=csv", "_blank");
  });

  btnExportJson.addEventListener("click", function () {
    window.open("/api/admin/report?format=json", "_blank");
  });

  // Tournament Reset Modal Handlers
  btnResetTournament.addEventListener("click", function () {
    resetConfirmInput.value = "";
    btnConfirmReset.disabled = true;
    resetModal.classList.remove("hidden");
  });

  btnCancelReset.addEventListener("click", function () {
    resetModal.classList.add("hidden");
  });

  resetConfirmInput.addEventListener("input", function () {
    btnConfirmReset.disabled = resetConfirmInput.value.trim() !== "RESET";
  });

  btnConfirmReset.addEventListener("click", function () {
    if (resetConfirmInput.value.trim() !== "RESET") return;
    resetModal.classList.add("hidden");
    send("init_default_tournament", {}, "Admin executed double-confirmed tournament reset");
    showToast("Tournament reset to default state.", false);
  });

  // ── Initialization & Session Check ───────────────────────────
  fetch("/api/admin/state", { credentials: "same-origin" })
    .then(function (res) {
      if (res.ok) {
        setAuthenticated(true);
      } else {
        setAuthenticated(false);
      }
    })
    .catch(function () {
      setAuthenticated(false);
    });

})();
