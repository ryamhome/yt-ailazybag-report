const numberFormatter = new Intl.NumberFormat("zh-TW");
const SNAPSHOT_MAX_AGE_MS = 96 * 60 * 60 * 1000;

function numericValue(value) {
  if (typeof value === "number") return Number.isFinite(value) && value >= 0 ? value : null;
  if (typeof value === "string" && /^\d+(?:\.\d+)?$/.test(value.trim())) return Number(value);
  return null;
}

function formatNumber(value) {
  const number = numericValue(value);
  return number === null ? "—" : numberFormatter.format(number);
}

function publicationKnown(video) {
  if (numericValue(video.age_days) !== null) return true;
  if (typeof video.published_at === "string" && Number.isFinite(Date.parse(video.published_at))) return true;
  return /(?:\d+\s*(?:分鐘|小時|天|週|個?月|年)前|\d+\s*(?:minute|hour|day|week|month|year)s?\s+ago|剛剛)/i.test(video.published_text || "");
}

function normalizeReport(raw, now = Date.now()) {
  const source = raw && typeof raw === "object" ? raw : {};
  const suppliedVideos = Array.isArray(source.videos) ? source.videos : [];
  const quality = { ...(source.data_quality || {}) };
  const legacyBroken = suppliedVideos.length > 0
    && suppliedVideos.every((video) => numericValue(video.views) === 0)
    && suppliedVideos.every((video) => !publicationKnown(video));
  const unknownViews = suppliedVideos.filter((video) => numericValue(video.views) === null).length;
  const unknownAges = suppliedVideos.filter((video) => !publicationKnown(video)).length;
  if (legacyBroken) {
    quality.status = "invalid";
    quality.message = "觀看數與發布時間來源異常；已停用成效判定，零值不代表實際觀看。";
  } else if (quality.status === "valid" && (unknownViews || unknownAges)) {
    quality.status = "partial";
    quality.message = "資料缺漏，暫停自動成效判讀。";
  } else if (!["valid", "partial", "invalid", "stale"].includes(quality.status)) {
    quality.status = !suppliedVideos.length ? "invalid" : unknownViews || unknownAges ? "partial" : "valid";
  }
  const generatedAt = Date.parse(source.generated_at || "");
  if (["valid", "partial"].includes(quality.status)
      && (!Number.isFinite(generatedAt) || now - generatedAt > SNAPSHOT_MAX_AGE_MS || generatedAt - now > 60 * 60 * 1000)) {
    quality.status = "stale";
    quality.message = "資料尚未更新；以下顯示的是上次快照，不代表目前表現。";
  }
  const invalid = quality.status === "invalid";
  const videos = suppliedVideos.map((video) => ({
    ...video,
    views: invalid ? null : numericValue(video.views),
    view_delta: invalid ? null : numericValue(video.view_delta),
    published_text: publicationKnown(video) ? video.published_text || "日期未提供" : "發布日期未知",
    age_days: publicationKnown(video) ? numericValue(video.age_days) : null,
  }));
  quality.known_view_count = videos.filter((video) => video.views !== null).length;
  quality.unknown_view_count = videos.length - quality.known_view_count;
  quality.unknown_age_count = unknownAges;
  quality.message = quality.message || ({
    valid: "觀看與發布資料已通過檢查。",
    partial: "部分資料缺失；未知值以 — 顯示，暫停自動成效建議。",
    invalid: "資料來源異常；暫停觀看統計與成效判定。",
    stale: "資料尚未更新；以下顯示上次快照。",
  })[quality.status];
  const completeViews = videos.length > 0 && videos.every((video) => video.views !== null);
  return {
    ...source,
    videos,
    scope: "latest_public_sample",
    sample_video_count: videos.length,
    public_view_total: completeViews ? videos.reduce((sum, video) => sum + video.views, 0) : null,
    data_quality: quality,
  };
}

function seriesSummary(videos) {
  const names = ["歷史謎案", "靈異檔案", "真實犯罪"];
  return names.map((name) => {
    const matches = videos.filter((video) => video.series === name);
    const unknown = matches.filter((video) => numericValue(video.views) === null).length;
    return {
      name,
      videos: matches.length,
      unknown,
      views: unknown ? null : matches.reduce((sum, video) => sum + numericValue(video.views), 0),
    };
  });
}

function reviewAvailable(data) {
  const review = data.weekly_review || {};
  return data.data_quality.status === "valid"
    && review.status === "available"
    && numericValue(review.mature_video_count) !== null
    && numericValue(review.target_met_count) !== null
    && data.videos.length > 0
    && data.videos.every((video) => numericValue(video.views) !== null && publicationKnown(video));
}

function taipeiTime(value) {
  const parsed = Date.parse(value || "");
  return Number.isFinite(parsed)
    ? new Date(parsed).toLocaleString("zh-TW", { timeZone: "Asia/Taipei", hour12: false })
    : "未提供";
}

function renderQuality(data) {
  const quality = data.data_quality;
  const names = { valid: "資料可用", partial: "資料不完整", invalid: "資料異常", stale: "資料未更新" };
  const badge = document.querySelector("#dataStatus");
  badge.textContent = names[quality.status];
  badge.className = `status-badge ${quality.status}`;
  document.querySelector("#dataStatusMessage").textContent = quality.message;
  document.querySelector("#dataCoverage").textContent = `本次樣本 ${formatNumber(data.sample_video_count)} 支，觀看數可讀取 ${formatNumber(quality.known_view_count)} 支；不代表頻道全部影片。`;
  document.querySelector("#dataSource").textContent = /YouTube Data API/i.test(data.source || "")
    ? "資料來源：YouTube Data API（公開欄位快照）"
    : "資料來源：YouTube 公開頻道頁快照";
  document.querySelector("#updatedAt").textContent = `資料快照：${taipeiTime(data.generated_at)}（台灣時間）`;
  const attempt = data.last_attempt_at || quality.checked_at;
  document.querySelector("#lastAttempt").textContent = attempt
    ? `最近檢查：${taipeiTime(attempt)}（台灣時間）`
    : "";
}

function renderMetrics(data) {
  const videos = data.videos;
  const complete = videos.length > 0 && videos.every((video) => numericValue(video.views) !== null);
  const topVideo = complete ? [...videos].sort((a, b) => b.views - a.views)[0] : null;
  document.querySelector("#videoCount").textContent = formatNumber(data.sample_video_count);
  document.querySelector("#viewTotal").textContent = formatNumber(data.public_view_total);
  document.querySelector("#subscriberCount").textContent = formatNumber(data.public_subscriber_count);
  document.querySelector("#topViews").textContent = topVideo ? formatNumber(topVideo.views) : "—";
  document.querySelector("#topTopic").textContent = topVideo ? topVideo.short_title : "觀看資料不完整";
}

function renderOwnerAnalytics(data) {
  const analytics = data.owner_analytics || {};
  const status = analytics.status || "not_connected";
  const messages = {
    available: "已連接頻道成效資料",
    reauthorization_required: "需要授權",
    not_connected: "尚未連接",
  };
  document.querySelector("#ownerAnalyticsStatus").textContent = messages[status] || "資料暫時不可用";
  document.querySelector("#ownerAnalyticsMessage").textContent = analytics.message || (status === "available"
    ? "只顯示來源實際提供的指標；未提供的資料以 — 顯示。"
    : "目前公開報表不含曝光、點閱率與留存；連接頻道擁有者成效資料後才會顯示。公開觀看數不能代替這些指標。");
  document.querySelector("#ownerAnalyticsPeriod").textContent = status === "available" ? analytics.period_label || "統計期間未提供" : "";
  const metrics = status === "available" ? analytics.metrics || analytics.summary || {} : {};
  document.querySelector("#ownerImpressions").textContent = formatNumber(metrics.impressions);
  const ctr = numericValue(metrics.impressions_ctr_percent);
  document.querySelector("#ownerCtr").textContent = ctr === null ? "—" : `${numberFormatter.format(ctr)}%`;
  const duration = numericValue(metrics.average_view_duration_seconds);
  document.querySelector("#ownerAverageDuration").textContent = duration === null ? "—" : `${numberFormatter.format(duration)} 秒`;
  const retention = numericValue(metrics.retention_30s_percent);
  document.querySelector("#ownerRetention").textContent = retention === null ? "—" : `${numberFormatter.format(retention)}%`;
}

function renderSeries(videos) {
  const container = document.querySelector("#seriesChart");
  const summary = seriesSummary(videos);
  const maximum = Math.max(...summary.map((item) => item.views || 0), 1);
  container.replaceChildren();
  summary.forEach((item) => {
    const row = document.createElement("div");
    row.className = "series-row";
    const description = item.views === null ? "觀看資料不完整" : `${formatNumber(item.views)} 次觀看`;
    row.innerHTML = `
      <span class="series-name">${item.name}</span>
      <div class="bar-track" aria-label="${item.name} ${description}">
        <div class="bar-fill" style="width: ${item.views === null ? 0 : (item.views / maximum) * 100}%"></div>
      </div>
      <span class="series-value">${formatNumber(item.views)} / ${item.videos}支</span>
    `;
    container.append(row);
  });
}

function renderReview(data) {
  const review = data.weekly_review || {};
  const available = reviewAvailable(data);
  const mature = numericValue(review.mature_video_count);
  const met = numericValue(review.target_met_count);
  document.querySelector("#reviewDate").textContent = review.review_date ? `檢討日期 ${review.review_date}` : "尚無檢討日期";
  document.querySelector("#reviewMet").textContent = available ? `${formatNumber(met)} / ${formatNumber(mature)}` : "—";
  document.querySelector("#reviewMature").textContent = available ? `已滿 7 天樣本影片｜階段目標 ${formatNumber(review.goal_views ?? 1000)} 次` : "等待可用觀看與發布日期";
  document.querySelector("#reviewSummary").textContent = available ? review.summary || "尚無足夠資料" : "資料不足，暫停七日成效判定與自動改善建議。";
  document.querySelector("#reviewLimit").textContent = review.limitations || "本報表僅為最新公開影片樣本，不能當成營利觀看時數或完整頻道成效。";
  const underperformerList = document.querySelector("#underperformerList");
  underperformerList.replaceChildren();
  const underperformers = available ? review.underperformers || [] : [];
  if (!underperformers.length) {
    const empty = document.createElement("p");
    empty.className = "review-empty";
    empty.textContent = !available ? "尚無足夠資料可判斷達標與否。" : mature ? "本期已滿七天的樣本沒有未達標影片。" : "已知發布日期的樣本尚未滿七天。";
    underperformerList.append(empty);
  } else {
    underperformers.forEach((video) => {
      const link = document.createElement("a");
      link.className = "review-video";
      link.href = video.url;
      link.target = "_blank";
      link.rel = "noreferrer";
      const title = document.createElement("strong");
      title.textContent = video.title;
      const stats = document.createElement("span");
      stats.textContent = `${formatNumber(video.views)} 次｜差 ${formatNumber(video.goal_gap)} 次`;
      link.append(title, stats);
      underperformerList.append(link);
    });
  }
  const strategyList = document.querySelector("#strategyList");
  strategyList.replaceChildren();
  const strategy = available ? review.next_video_strategy || {} : {};
  const directives = [...(strategy.packaging_directives || []), ...(strategy.script_directives || []), ...(strategy.image_directives || [])];
  if (!available) directives.push("先恢復正確數據，再依曝光、點閱與留存判斷下一輪調整。");
  directives.slice(0, 6).forEach((directive) => {
    const item = document.createElement("li");
    item.textContent = directive;
    strategyList.append(item);
  });
}

function renderVideos(videos) {
  const grid = document.querySelector("#videoGrid");
  const template = document.querySelector("#videoCardTemplate");
  grid.replaceChildren();
  videos.forEach((video) => {
    const card = template.content.cloneNode(true);
    const thumbnailLink = card.querySelector(".thumbnail-link");
    const thumbnail = card.querySelector(".thumbnail");
    const title = card.querySelector(".video-title");
    thumbnailLink.href = video.url;
    thumbnail.src = video.thumbnail_url;
    thumbnail.alt = `${video.short_title}影片縮圖`;
    title.href = video.url;
    title.textContent = video.title;
    card.querySelector(".duration").textContent = video.duration || "—";
    card.querySelector(".series-pill").textContent = video.series;
    card.querySelector(".published").textContent = video.published_text || "發布日期未知";
    card.querySelector(".views").textContent = formatNumber(video.views);
    const delta = card.querySelector(".delta");
    const change = numericValue(video.view_delta);
    if (change !== null && change > 0) {
      delta.textContent = `+${formatNumber(change)} 次`;
      delta.classList.add("positive");
    } else {
      delta.textContent = change === null ? "差異資料未提供" : "本期無增加";
    }
    grid.append(card);
  });
}

function renderError() {
  document.querySelector("#dataStatus").textContent = "資料暫時不可用";
  document.querySelector("#dataStatus").className = "status-badge invalid";
  document.querySelector("#dataStatusMessage").textContent = "無法讀取報告；暫停顯示成效結論。";
  document.querySelector("#metricGrid").innerHTML = '<p class="error-state">目前無法讀取公開報告，請稍後重新整理。</p>';
  document.querySelector("#seriesChart").innerHTML = '<p class="error-state">資料暫時無法顯示。</p>';
  document.querySelector("#videoGrid").innerHTML = '<p class="error-state">影片資料暫時無法顯示。</p>';
  document.querySelector("#reviewSummary").textContent = "資料不足，暫停七日成效判定與自動改善建議。";
  document.querySelector("#ownerAnalyticsStatus").textContent = "資料暫時不可用";
}

function renderReport(raw) {
  const data = normalizeReport(raw);
  renderQuality(data);
  renderMetrics(data);
  renderOwnerAnalytics(data);
  renderReview(data);
  renderSeries(data.videos);
  renderVideos(data.videos);
}

if (typeof document !== "undefined") {
  fetch("data.json", { cache: "no-store" })
    .then((response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    })
    .then(renderReport)
    .catch((error) => {
      console.error("Public report failed to load", error);
      renderError();
    });
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { numericValue, formatNumber, publicationKnown, normalizeReport, seriesSummary, reviewAvailable, renderMetrics, renderOwnerAnalytics, renderReview, renderQuality };
}
