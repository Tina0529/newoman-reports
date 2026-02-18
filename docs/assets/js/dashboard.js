/**
 * dashboard.js - Chart rendering, period selection, data loading, multi-client support
 */
(function() {
    let dashboardData = null;
    let filteredMonths = [];
    let trendChart = null;
    let volumeChart = null;
    let weekdayChart = null;
    let clientList = []; // [{slug, name, hidden?}]

    // UTF-8 safe base64 helpers
    function utf8ToBase64(str) {
        return btoa(unescape(encodeURIComponent(str)));
    }
    function base64ToUtf8(b64) {
        return decodeURIComponent(escape(atob(b64)));
    }

    // Detect client slug from URL or default
    function getClientSlug() {
        const params = new URLSearchParams(window.location.search);
        return params.get('client') || 'newoman-takanawa';
    }

    // Format year_month "2025-09" → "2025/09"
    function fmtMonth(ym) {
        return ym.replace('-', '/');
    }

    // Persist hidden slugs locally so deletions take effect before GitHub Pages redeploys
    function getLocalHiddenSlugs() {
        try {
            return JSON.parse(localStorage.getItem('hidden_client_slugs') || '[]');
        } catch (e) { return []; }
    }
    function addLocalHiddenSlug(slug) {
        const hidden = getLocalHiddenSlugs();
        if (!hidden.includes(slug)) {
            hidden.push(slug);
            localStorage.setItem('hidden_client_slugs', JSON.stringify(hidden));
        }
    }
    function removeLocalHiddenSlug(slug) {
        const hidden = getLocalHiddenSlugs().filter(s => s !== slug);
        localStorage.setItem('hidden_client_slugs', JSON.stringify(hidden));
    }

    async function loadClientList() {
        try {
            const resp = await fetch('clients/clients.json');
            if (resp.ok) {
                clientList = await resp.json();
            }
        } catch (e) {
            // clients.json not found — build from current data only
        }
        // Apply local hidden state (covers gap before GitHub Pages redeploys)
        const localHidden = getLocalHiddenSlugs();
        clientList.forEach(c => {
            if (localHidden.includes(c.slug)) c.hidden = true;
            // If server says hidden but not in local list, sync local → server won
            // If server says NOT hidden and local says hidden, local wins (fresher)
        });
        // Sync: if server already has hidden=true, remove from local cache (server caught up)
        clientList.forEach(c => {
            if (c.hidden && !localHidden.includes(c.slug)) {
                // Server already hidden, no need for local override
            }
        });
        // Clean up local hidden slugs that server now reflects
        const serverHiddenSlugs = clientList.filter(c => c.hidden).map(c => c.slug);
        const cleanedLocal = localHidden.filter(s => !serverHiddenSlugs.includes(s));
        if (cleanedLocal.length !== localHidden.length) {
            localStorage.setItem('hidden_client_slugs', JSON.stringify(cleanedLocal));
        }

        // Ensure current client is in the list
        const currentSlug = getClientSlug();
        if (!clientList.find(c => c.slug === currentSlug)) {
            clientList.push({ slug: currentSlug, name: currentSlug });
        }
    }

    function getVisibleClients() {
        return clientList.filter(c => !c.hidden);
    }

    function populateClientSelector() {
        const sel = document.getElementById('client-selector');
        sel.innerHTML = '';
        const currentSlug = getClientSlug();
        getVisibleClients().forEach(c => {
            const opt = new Option(c.name, c.slug);
            sel.appendChild(opt);
        });
        sel.value = currentSlug;
        sel.addEventListener('change', function() {
            const newSlug = sel.value;
            const url = new URL(window.location);
            url.searchParams.set('client', newSlug);
            window.location.href = url.toString();
        });
    }

    function renderClientManagement() {
        const container = document.getElementById('client-management-list');
        if (!container) return;
        const isJa = window.i18n && window.i18n.current() === 'ja';
        const visible = getVisibleClients();
        if (visible.length === 0) {
            container.innerHTML = `<p style="color:var(--text-muted);font-size:13px;">${isJa ? 'クライアントがありません' : '没有客户'}</p>`;
            return;
        }
        container.innerHTML = visible.map(c => `
            <div class="client-item">
                <div class="client-item-info">
                    <span class="client-item-name">${c.name}</span>
                    <span class="client-item-slug">${c.slug}</span>
                </div>
                <button class="btn btn-ghost btn-sm client-delete-btn" data-slug="${c.slug}" title="${isJa ? '削除' : '删除'}">✕</button>
            </div>
        `).join('');

        container.querySelectorAll('.client-delete-btn').forEach(btn => {
            btn.addEventListener('click', function() {
                const slug = this.dataset.slug;
                const client = clientList.find(c => c.slug === slug);
                const confirmMsg = isJa
                    ? `「${client.name}」を削除しますか？（データは保持されます）`
                    : `确定删除「${client.name}」吗？（数据会保留）`;
                if (confirm(confirmMsg)) {
                    deleteClient(slug);
                }
            });
        });
    }

    async function loadData() {
        const slug = getClientSlug();
        try {
            const resp = await fetch(`clients/${slug}/dashboard-data.json`);
            if (!resp.ok) throw new Error('Data not found');
            dashboardData = await resp.json();
            return true;
        } catch (e) {
            console.error('Failed to load dashboard data:', e);
            return false;
        }
    }

    function populatePeriodSelectors() {
        const startSel = document.getElementById('period-start');
        const endSel = document.getElementById('period-end');
        startSel.innerHTML = '';
        endSel.innerHTML = '';

        const months = dashboardData.months;
        months.forEach(m => {
            const opt1 = new Option(m.period, m.year_month);
            const opt2 = new Option(m.period, m.year_month);
            startSel.appendChild(opt1);
            endSel.appendChild(opt2);
        });

        // Default: show all months
        if (months.length > 0) {
            startSel.value = months[0].year_month;
            endSel.value = months[months.length - 1].year_month;
        }
    }

    function getFilteredMonths() {
        const start = document.getElementById('period-start').value;
        const end = document.getElementById('period-end').value;
        return dashboardData.months.filter(m => m.year_month >= start && m.year_month <= end);
    }

    function formatTrend(current, previous, suffix, inverse) {
        if (previous === undefined || previous === null) return { text: '', cls: 'neutral' };
        const diff = current - previous;
        if (Math.abs(diff) < 0.1) return { text: '-', cls: 'neutral' };
        const arrow = diff > 0 ? '\u2191' : '\u2193';
        let cls;
        if (inverse) {
            cls = diff > 0 ? 'down' : 'up';
        } else {
            cls = diff > 0 ? 'up' : 'down';
        }
        return { text: `${arrow} ${Math.abs(diff).toFixed(1)}${suffix}`, cls };
    }

    function updateKPIs(months) {
        if (months.length === 0) return;

        const latest = months[months.length - 1];
        const prev = months.length > 1 ? months[months.length - 2] : null;

        // Aggregate for multi-month
        const totalMsgs = months.reduce((s, m) => s + m.total_messages, 0);
        const avgAnswerRate = months.reduce((s, m) => s + m.normal_answer_rate, 0) / months.length;
        const avgUnanswered = months.reduce((s, m) => s + m.unanswered_rate, 0) / months.length;
        const avgGoodRate = months.reduce((s, m) => s + m.good_rating_rate, 0) / months.length;
        const avgFeedback = months.reduce((s, m) => s + m.feedback_rate, 0) / months.length;
        const avgDaily = months.reduce((s, m) => s + m.daily_average, 0) / months.length;

        document.getElementById('kpi-total').textContent = totalMsgs.toLocaleString();
        document.getElementById('kpi-answer-rate').textContent = avgAnswerRate.toFixed(1) + '%';
        document.getElementById('kpi-unanswered').textContent = avgUnanswered.toFixed(1) + '%';
        document.getElementById('kpi-good-rate').textContent = avgGoodRate.toFixed(1) + '%';
        document.getElementById('kpi-feedback').textContent = avgFeedback.toFixed(1) + '%';
        document.getElementById('kpi-daily-avg').textContent = avgDaily.toFixed(1);

        // Trends (compare latest to previous month)
        if (prev) {
            const trends = [
                { id: 'kpi-total-trend', cur: latest.total_messages, prev: prev.total_messages, suf: '', inv: false },
                { id: 'kpi-answer-trend', cur: latest.normal_answer_rate, prev: prev.normal_answer_rate, suf: '%', inv: false },
                { id: 'kpi-unanswered-trend', cur: latest.unanswered_rate, prev: prev.unanswered_rate, suf: '%', inv: true },
                { id: 'kpi-good-trend', cur: latest.good_rating_rate, prev: prev.good_rating_rate, suf: '%', inv: false },
                { id: 'kpi-feedback-trend', cur: latest.feedback_rate, prev: prev.feedback_rate, suf: '%', inv: false },
                { id: 'kpi-daily-trend', cur: latest.daily_average, prev: prev.daily_average, suf: '', inv: false },
            ];
            trends.forEach(t => {
                const trend = formatTrend(t.cur, t.prev, t.suf, t.inv);
                const el = document.getElementById(t.id);
                el.textContent = trend.text;
                el.className = 'kpi-trend ' + trend.cls;
            });
        }
    }

    function renderTrendChart(months) {
        const container = document.getElementById('chart-trend');
        if (!trendChart) {
            trendChart = echarts.init(container);
            window.addEventListener('resize', () => trendChart.resize());
        }

        const categories = months.map(m => fmtMonth(m.year_month));
        const isJa = window.i18n && window.i18n.current() === 'ja';

        trendChart.setOption({
            tooltip: { trigger: 'axis' },
            legend: {
                data: [
                    isJa ? '正常回答率' : '正常回答率',
                    isJa ? '未回答率' : '未回答率',
                    isJa ? '好評価率' : '好评率',
                    isJa ? 'フィードバック率' : '反馈率',
                ],
                bottom: 0,
                textStyle: { fontSize: 12 },
            },
            grid: { left: 50, right: 20, top: 20, bottom: 60 },
            xAxis: {
                type: 'category',
                data: categories,
                axisLabel: { interval: 0 },
            },
            yAxis: { type: 'value', axisLabel: { formatter: '{value}%' }, max: 100 },
            series: [
                {
                    name: isJa ? '正常回答率' : '正常回答率',
                    type: 'line', smooth: true,
                    data: months.map(m => m.normal_answer_rate),
                    itemStyle: { color: '#3B82F6' },
                    lineStyle: { width: 3 },
                },
                {
                    name: isJa ? '未回答率' : '未回答率',
                    type: 'line', smooth: true,
                    data: months.map(m => m.unanswered_rate),
                    itemStyle: { color: '#EF4444' },
                    lineStyle: { width: 2, type: 'dashed' },
                },
                {
                    name: isJa ? '好評価率' : '好评率',
                    type: 'line', smooth: true,
                    data: months.map(m => m.good_rating_rate),
                    itemStyle: { color: '#10B981' },
                    lineStyle: { width: 2 },
                },
                {
                    name: isJa ? 'フィードバック率' : '反馈率',
                    type: 'line', smooth: true,
                    data: months.map(m => m.feedback_rate),
                    itemStyle: { color: '#F59E0B' },
                    lineStyle: { width: 2 },
                },
            ],
        });
    }

    function renderVolumeChart(months) {
        const container = document.getElementById('chart-volume');
        if (!volumeChart) {
            volumeChart = echarts.init(container);
            window.addEventListener('resize', () => volumeChart.resize());
        }

        const isJa = window.i18n && window.i18n.current() === 'ja';

        volumeChart.setOption({
            tooltip: { trigger: 'axis' },
            legend: {
                data: [isJa ? '総メッセージ数' : '总消息数', isJa ? '日平均' : '日均'],
                bottom: 0,
            },
            grid: { left: 60, right: 60, top: 40, bottom: 50 },
            xAxis: {
                type: 'category',
                data: months.map(m => fmtMonth(m.year_month)),
                axisLabel: { interval: 0 },
            },
            yAxis: [
                { type: 'value', name: isJa ? '件数' : '件数', position: 'left', nameTextStyle: { padding: [0, 0, 0, 0] } },
                { type: 'value', name: isJa ? '日平均' : '日均', position: 'right', nameTextStyle: { padding: [0, 0, 0, 0] } },
            ],
            series: [
                {
                    name: isJa ? '総メッセージ数' : '总消息数',
                    type: 'bar',
                    data: months.map(m => m.total_messages),
                    itemStyle: { color: '#3B82F6', borderRadius: [4, 4, 0, 0] },
                    barMaxWidth: 40,
                },
                {
                    name: isJa ? '日平均' : '日均',
                    type: 'line',
                    yAxisIndex: 1,
                    data: months.map(m => m.daily_average),
                    itemStyle: { color: '#F59E0B' },
                    lineStyle: { width: 2 },
                },
            ],
        });
    }

    function renderWeekdayChart(months) {
        const container = document.getElementById('chart-weekday');
        if (!weekdayChart) {
            weekdayChart = echarts.init(container);
            window.addEventListener('resize', () => weekdayChart.resize());
        }

        const isJa = window.i18n && window.i18n.current() === 'ja';
        const weekdayLabels = isJa
            ? ['月', '火', '水', '木', '金', '土', '日']
            : ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];

        // Aggregate weekday_counts across selected months
        const totals = [0, 0, 0, 0, 0, 0, 0];
        months.forEach(m => {
            if (m.weekday_counts && m.weekday_counts.length === 7) {
                for (let i = 0; i < 7; i++) {
                    totals[i] += m.weekday_counts[i];
                }
            }
        });

        weekdayChart.setOption({
            tooltip: {
                trigger: 'axis',
                formatter: function(params) {
                    const p = params[0];
                    return p.name + ': ' + p.value + (isJa ? '件' : '条');
                },
            },
            grid: { left: 50, right: 20, top: 20, bottom: 30 },
            xAxis: {
                type: 'category',
                data: weekdayLabels,
                axisLabel: { interval: 0 },
            },
            yAxis: { type: 'value' },
            series: [{
                type: 'bar',
                data: totals,
                itemStyle: {
                    color: function(params) {
                        // Sat/Sun in different color
                        return params.dataIndex >= 5 ? '#F59E0B' : '#3B82F6';
                    },
                    borderRadius: [4, 4, 0, 0],
                },
                barMaxWidth: 40,
            }],
        });
    }

    function renderReportLinks(months) {
        const container = document.getElementById('report-list');
        const isJa = window.i18n && window.i18n.current() === 'ja';
        const slug = getClientSlug();

        container.innerHTML = months.slice().reverse().map(m => {
            const reportUrl = `clients/${slug}/${m.report_file}`;
            return `
                <a href="${reportUrl}" class="report-card">
                    <div class="report-month">${m.period}</div>
                    <div class="report-total">${(isJa ? '総数: ' : '总数: ') + m.total_messages.toLocaleString() + (isJa ? '件' : '条')}</div>
                    <div class="report-rate">${(isJa ? '回答率: ' : '回答率: ') + m.normal_answer_rate + '%'}</div>
                </a>
            `;
        }).join('');
    }

    function updateDashboard() {
        filteredMonths = getFilteredMonths();
        if (filteredMonths.length === 0) return;

        updateKPIs(filteredMonths);
        renderTrendChart(filteredMonths);
        renderVolumeChart(filteredMonths);
        renderWeekdayChart(filteredMonths);
        renderReportLinks(filteredMonths);
    }

    // ========================================
    // Admin: GitHub Actions workflow trigger
    // ========================================

    const GITHUB_REPO = 'Tina0529/newoman-reports';
    const WORKFLOW_FILE = 'update-report.yml';

    function showAdminStatus(type, message) {
        const status = document.getElementById('admin-status');
        status.style.display = 'block';
        status.className = 'admin-status ' + type;
        status.textContent = message;
    }

    async function triggerWorkflow() {
        const clientName = document.getElementById('admin-client-name').value.trim();
        let clientSlug = document.getElementById('admin-client-slug').value.trim().toLowerCase();
        // Auto-update the field to show the normalized slug
        document.getElementById('admin-client-slug').value = clientSlug;
        const datasetId = document.getElementById('admin-dataset-id').value.trim();
        const apiToken = document.getElementById('admin-api-token').value.trim();
        const githubToken = document.getElementById('admin-github-token').value.trim();
        const month = document.getElementById('admin-month').value;
        const isJa = window.i18n && window.i18n.current() === 'ja';

        if (!clientName || !clientSlug || !datasetId || !apiToken || !githubToken || !month) {
            showAdminStatus('error', isJa
                ? 'すべてのフィールドを入力してください。'
                : '请填写所有字段。');
            return;
        }

        // Validate slug format (lowercase, hyphens, no spaces)
        if (!/^[a-z0-9-]+$/.test(clientSlug)) {
            showAdminStatus('error', isJa
                ? 'Slugは半角英数字とハイフンのみ使用できます（例: newoman-takanawa）'
                : 'Slug只能使用小写英文字母、数字和连字符（例: newoman-takanawa）');
            return;
        }

        // Save credentials for convenience
        localStorage.setItem('admin_client_name', clientName);
        localStorage.setItem('admin_client_slug', clientSlug);
        localStorage.setItem('admin_dataset_id', datasetId);
        sessionStorage.setItem('admin_api_token', apiToken);
        sessionStorage.setItem('admin_github_token', githubToken);

        showAdminStatus('loading', isJa
            ? 'ワークフローを起動中...'
            : '正在启动工作流...');

        try {
            const resp = await fetch(
                `https://api.github.com/repos/${GITHUB_REPO}/actions/workflows/${WORKFLOW_FILE}/dispatches`,
                {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${githubToken}`,
                        'Accept': 'application/vnd.github.v3+json',
                    },
                    body: JSON.stringify({
                        ref: 'main',
                        inputs: {
                            dataset_id: datasetId,
                            api_token: apiToken,
                            month: month,
                            client_name: clientName,
                            client_slug: clientSlug,
                        },
                    }),
                }
            );

            if (resp.status === 204) {
                showAdminStatus('loading', isJa
                    ? 'ワークフローを起動しました。進捗を確認中...'
                    : '工作流已启动，正在检查进度...');
                pollWorkflowStatus(githubToken, isJa, clientName, clientSlug);
            } else if (resp.status === 401 || resp.status === 403) {
                showAdminStatus('error', isJa
                    ? 'GitHub Tokenが無効です。repo権限のあるPATを使用してください。'
                    : 'GitHub Token无效，请使用具有repo权限的PAT。');
            } else if (resp.status === 404) {
                showAdminStatus('error', isJa
                    ? 'ワークフローが見つかりません。リポジトリにupdate-report.ymlが存在するか確認してください。'
                    : '未找到工作流，请确认仓库中存在update-report.yml。');
            } else {
                const errText = await resp.text();
                showAdminStatus('error', `Error ${resp.status}: ${errText}`);
            }
        } catch (e) {
            showAdminStatus('error', isJa
                ? `ネットワークエラー: ${e.message}`
                : `网络错误: ${e.message}`);
        }
    }

    function pollWorkflowStatus(githubToken, isJa, clientName, clientSlug) {
        let attempts = 0;
        const maxAttempts = 60; // 10 minutes max (10s interval)

        const poll = async () => {
            attempts++;
            if (attempts > maxAttempts) {
                showAdminStatus('error', isJa
                    ? 'タイムアウト: GitHubのActionsタブで状態を確認してください。'
                    : '超时：请在GitHub Actions页面查看状态。');
                return;
            }

            try {
                const resp = await fetch(
                    `https://api.github.com/repos/${GITHUB_REPO}/actions/runs?per_page=1&event=workflow_dispatch`,
                    { headers: { 'Authorization': `Bearer ${githubToken}` } }
                );
                const data = await resp.json();

                if (!data.workflow_runs || data.workflow_runs.length === 0) {
                    setTimeout(poll, 10000);
                    return;
                }

                const run = data.workflow_runs[0];

                if (run.status === 'completed') {
                    if (run.conclusion === 'success') {
                        // Update clients.json with the new client
                        updateClientsJson(githubToken, clientName, clientSlug);
                        const switchUrl = `?client=${clientSlug}`;
                        showAdminStatus('success', isJa
                            ? `更新完了！ 「${clientName}」のダッシュボードを表示するにはページを更新してください。`
                            : `更新完成！请刷新页面查看「${clientName}」的看板。`);
                    } else {
                        showAdminStatus('error', isJa
                            ? `ワークフロー失敗: ${run.conclusion}。GitHubのActionsタブで詳細を確認してください。`
                            : `工作流失败: ${run.conclusion}。请在GitHub Actions页面查看详情。`);
                    }
                    return;
                }

                // Still running
                const elapsed = Math.round((Date.now() - new Date(run.created_at).getTime()) / 1000);
                showAdminStatus('loading', isJa
                    ? `実行中... (${elapsed}秒経過)`
                    : `执行中... (已经过${elapsed}秒)`);
                setTimeout(poll, 10000);
            } catch (e) {
                setTimeout(poll, 10000);
            }
        };

        setTimeout(poll, 5000); // First check after 5s
    }

    // Read clients.json from GitHub API (returns {data, sha})
    async function readClientsJsonFromGitHub(githubToken) {
        let data = [];
        let sha = null;
        try {
            const getResp = await fetch(
                `https://api.github.com/repos/${GITHUB_REPO}/contents/docs/clients/clients.json`,
                { headers: { 'Authorization': `Bearer ${githubToken}` } }
            );
            if (getResp.ok) {
                const fileData = await getResp.json();
                sha = fileData.sha;
                data = JSON.parse(base64ToUtf8(fileData.content));
            }
        } catch (e) { /* file doesn't exist yet */ }
        return { data, sha };
    }

    // Write clients.json to GitHub API
    async function writeClientsJsonToGitHub(githubToken, data, sha, message) {
        const body = {
            message: message,
            content: utf8ToBase64(JSON.stringify(data, null, 2)),
        };
        if (sha) body.sha = sha;

        await fetch(
            `https://api.github.com/repos/${GITHUB_REPO}/contents/docs/clients/clients.json`,
            {
                method: 'PUT',
                headers: {
                    'Authorization': `Bearer ${githubToken}`,
                    'Accept': 'application/vnd.github.v3+json',
                },
                body: JSON.stringify(body),
            }
        );
    }

    // Update clients.json via GitHub API after workflow success
    async function updateClientsJson(githubToken, clientName, clientSlug) {
        try {
            const { data: existing, sha } = await readClientsJsonFromGitHub(githubToken);

            const found = existing.find(c => c.slug === clientSlug);
            if (found) {
                // Re-activate if hidden, update name
                if (found.hidden || found.name !== clientName) {
                    found.hidden = false;
                    found.name = clientName;
                    await writeClientsJsonToGitHub(githubToken, existing, sha, `Update client: ${clientName}`);
                }
            } else {
                existing.push({ slug: clientSlug, name: clientName });
                existing.sort((a, b) => a.name.localeCompare(b.name));
                await writeClientsJsonToGitHub(githubToken, existing, sha, `Add client: ${clientName}`);
            }
            // Clear from local hidden cache (client is now active)
            removeLocalHiddenSlug(clientSlug);
        } catch (e) {
            console.error('Failed to update clients.json:', e);
        }
    }

    // Logical delete: set hidden=true in clients.json
    async function deleteClient(slug) {
        const githubToken = sessionStorage.getItem('admin_github_token');
        const isJa = window.i18n && window.i18n.current() === 'ja';

        if (!githubToken) {
            showAdminStatus('error', isJa
                ? 'GitHub Tokenが必要です。管理パネルにTokenを入力してください。'
                : '需要GitHub Token，请在管理面板中输入Token。');
            return;
        }

        showAdminStatus('loading', isJa ? '削除中...' : '删除中...');

        try {
            const { data: existing, sha } = await readClientsJsonFromGitHub(githubToken);
            const client = existing.find(c => c.slug === slug);
            if (client) {
                client.hidden = true;
                await writeClientsJsonToGitHub(githubToken, existing, sha, `Hide client: ${client.name}`);

                // Persist locally so deletion survives page reload before GitHub Pages redeploys
                addLocalHiddenSlug(slug);

                // Update local state
                const local = clientList.find(c => c.slug === slug);
                if (local) local.hidden = true;

                // Clear admin form fields if they match the deleted client
                const adminSlugField = document.getElementById('admin-client-slug');
                if (adminSlugField && adminSlugField.value === slug) {
                    document.getElementById('admin-client-name').value = '';
                    adminSlugField.value = '';
                    document.getElementById('admin-dataset-id').value = '';
                    localStorage.removeItem('admin_client_name');
                    localStorage.removeItem('admin_client_slug');
                    localStorage.removeItem('admin_dataset_id');
                }

                // Re-render client selector and management list
                populateClientSelector();
                renderClientManagement();

                showAdminStatus('success', isJa
                    ? `「${client.name}」を削除しました。`
                    : `已删除「${client.name}」。`);

                // If we just deleted the current client, switch to first visible
                if (getClientSlug() === slug) {
                    const visible = getVisibleClients();
                    if (visible.length > 0) {
                        const url = new URL(window.location);
                        url.searchParams.set('client', visible[0].slug);
                        setTimeout(() => { window.location.href = url.toString(); }, 1500);
                    }
                }
            }
        } catch (e) {
            showAdminStatus('error', isJa
                ? `削除エラー: ${e.message}`
                : `删除错误: ${e.message}`);
        }
    }

    // ========================================
    // Init
    // ========================================

    window.initDashboard = async function() {
        await loadClientList();

        // If current client is hidden (deleted), redirect to first visible client
        const currentSlug = getClientSlug();
        const currentClient = clientList.find(c => c.slug === currentSlug);
        if (currentClient && currentClient.hidden) {
            const visible = getVisibleClients();
            if (visible.length > 0) {
                const url = new URL(window.location);
                url.searchParams.set('client', visible[0].slug);
                window.location.href = url.toString();
                return;
            }
        }

        populateClientSelector();

        const success = await loadData();
        if (!success) {
            document.getElementById('app').innerHTML = '<div style="text-align:center;padding:60px;"><h2>Data not available</h2><p>dashboard-data.json not found</p></div>';
            return;
        }

        // Set header
        document.getElementById('client-name').textContent = dashboardData.client;
        if (dashboardData.updated_at) {
            const d = new Date(dashboardData.updated_at);
            const isJa = window.i18n && window.i18n.current() === 'ja';
            document.getElementById('updated-at').textContent =
                (isJa ? '最終更新: ' : '最后更新: ') + d.toLocaleDateString('ja-JP');
        }

        // Update client name in client list if we have real data
        const clientInList = clientList.find(c => c.slug === currentSlug);
        if (clientInList && clientInList.name === currentSlug && dashboardData.client) {
            clientInList.name = dashboardData.client;
            populateClientSelector();
        }

        populatePeriodSelectors();
        updateDashboard();

        // Period apply button
        document.getElementById('period-apply').addEventListener('click', updateDashboard);

        // Restore saved admin credentials
        const savedClientName = localStorage.getItem('admin_client_name');
        if (savedClientName) document.getElementById('admin-client-name').value = savedClientName;
        const savedClientSlug = localStorage.getItem('admin_client_slug');
        if (savedClientSlug) document.getElementById('admin-client-slug').value = savedClientSlug;
        const savedDatasetId = localStorage.getItem('admin_dataset_id');
        if (savedDatasetId) document.getElementById('admin-dataset-id').value = savedDatasetId;
        const savedApiToken = sessionStorage.getItem('admin_api_token');
        if (savedApiToken) document.getElementById('admin-api-token').value = savedApiToken;
        const savedGithubToken = sessionStorage.getItem('admin_github_token');
        if (savedGithubToken) document.getElementById('admin-github-token').value = savedGithubToken;

        // Admin update button
        document.getElementById('admin-update').addEventListener('click', triggerWorkflow);

        // Render client management list in admin panel
        renderClientManagement();
    };

    // Auto-init if already authenticated
    document.addEventListener('DOMContentLoaded', function() {
        if (sessionStorage.getItem('dashboard_authenticated') === 'true') {
            if (document.getElementById('app').style.display !== 'none') {
                window.initDashboard();
            }
        }
    });
})();
