const numberFormatter = new Intl.NumberFormat("zh-TW");

function formatNumber(value) {
  return numberFormatter.format(Number(value || 0));
}

function seriesSummary(videos) {
  const names = ["歷史謎案", "靈異檔案", "真實犯罪"];
  return names.map((name) => {
    const matches = videos.filter((video) => video.series === name);
    return {
      name,
      videos: matches.length,
      views: matches.reduce((sum, video) => sum + Number(video.views || 0), 0),
    };
  });
}

function renderMetrics(data) {
  const videos = data.videos || [];
  const topVideo = [...videos].sort((a, b) => Number(b.views) - Number(a.views))[0];
  document.querySelector("#videoCount").textContent = formatNumber(data.public_video_count);
  document.querySelector("#viewTotal").textContent = formatNumber(data.public_view_total);
  document.querySelector("#subscriberCount").textContent = data.public_subscriber_count ?? "-";
  document.querySelector("#topViews").textContent = topVideo ? formatNumber(topVideo.views) : "-";
  document.querySelector("#topTopic").textContent = topVideo ? topVideo.short_title : "尚無公開影片";

  const updated = new Date(data.generated_at);
  document.querySelector("#updatedAt").textContent = Number.isNaN(updated.getTime())
    ? `資料日期 ${data.report_date}`
    : `更新於 ${updated.toLocaleString("zh-TW", { timeZone: "Asia/Taipei", hour12: false })}`;
}

function renderSeries(videos) {
  const container = document.querySelector("#seriesChart");
  const summary = seriesSummary(videos);
  const maximum = Math.max(...summary.map((item) => item.views), 1);
  container.replaceChildren();

  summary.forEach((item) => {
    const row = document.createElement("div");
    row.className = "series-row";
    row.innerHTML = `
      <span class="series-name">${item.name}</span>
      <div class="bar-track" aria-label="${item.name} ${item.views} 次觀看">
        <div class="bar-fill" style="width: ${(item.views / maximum) * 100}%"></div>
      </div>
      <span class="series-value">${formatNumber(item.views)} / ${item.videos}支</span>
    `;
    container.append(row);
  });
}

function renderReview(data) {
  const review = data.weekly_review || {};
  const mature = Number(review.mature_video_count || 0);
  const met = Number(review.target_met_count || 0);
  document.querySelector("#reviewDate").textContent = review.review_date
    ? `檢討日期 ${review.review_date}`
    : "尚無檢討日期";
  document.querySelector("#reviewMet").textContent = `${met} / ${mature}`;
  document.querySelector("#reviewMature").textContent = `已滿 7 天影片｜目標 ${formatNumber(review.goal_views || 1000)} 次`;
  document.querySelector("#reviewSummary").textContent = review.summary || "尚無足夠資料";
  document.querySelector("#reviewLimit").textContent = review.limitations || "";

  const underperformerList = document.querySelector("#underperformerList");
  const underperformers = review.underperformers || [];
  underperformerList.replaceChildren();
  if (!underperformers.length) {
    const empty = document.createElement("p");
    empty.className = "review-empty";
    empty.textContent = mature ? "本期沒有未達標影片" : "尚無發布滿 7 天影片";
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
  const strategy = review.next_video_strategy || {};
  const directives = [
    ...(strategy.packaging_directives || []),
    ...(strategy.script_directives || []),
    ...(strategy.image_directives || []),
  ];
  strategyList.replaceChildren();
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
    card.querySelector(".duration").textContent = video.duration || "-";
    card.querySelector(".series-pill").textContent = video.series;
    card.querySelector(".published").textContent = video.published_text;
    card.querySelector(".views").textContent = formatNumber(video.views);
    const delta = card.querySelector(".delta");
    if (Number(video.view_delta) > 0) {
      delta.textContent = `+${formatNumber(video.view_delta)} 次`;
      delta.classList.add("positive");
    } else {
      delta.textContent = "本期追蹤";
    }
    grid.append(card);
  });
}

function renderError() {
  document.querySelector("#metricGrid").innerHTML = '<p class="error-state">目前無法讀取公開報告，請稍後重新整理。</p>';
  document.querySelector("#seriesChart").innerHTML = '<p class="error-state">資料暫時無法顯示。</p>';
  document.querySelector("#videoGrid").innerHTML = '<p class="error-state">影片資料暫時無法顯示。</p>';
}

fetch("data.json", { cache: "no-store" })
  .then((response) => {
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  })
  .then((data) => {
    renderMetrics(data);
    renderReview(data);
    renderSeries(data.videos || []);
    renderVideos(data.videos || []);
  })
  .catch((error) => {
    console.error("Public report failed to load", error);
    renderError();
  });
