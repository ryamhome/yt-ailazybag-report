"""Exercise browser display behavior against missing, stale and broken data."""
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("node"), "Node.js is required for dashboard behavior checks")
class DashboardBehaviorTests(unittest.TestCase):
    def test_unknown_zero_quality_and_rendering(self) -> None:
        script = r'''
const assert = require("node:assert/strict");
const ui = require("./docs/app.js");
const now = Date.parse("2026-10-20T12:00:00+08:00");
const fresh = "2026-10-20T10:30:00+08:00";
const review = {status: "available", mature_video_count: 1, target_met_count: 0, summary: "正確觀察", underperformers: [], next_video_strategy: {script_directives: ["有效建議"]}};
function video(views, published_text = "8 天前") {
  return {video_id: "abc", title: "測試", short_title: "測試", series: "歷史謎案", views, published_text};
}
assert.equal(ui.formatNumber(null), "—");
assert.equal(ui.formatNumber(undefined), "—");
assert.equal(ui.formatNumber(""), "—");
assert.equal(ui.formatNumber(false), "—");
assert.equal(ui.formatNumber(-1), "—");
assert.equal(ui.formatNumber(0), "0");
assert.equal(ui.formatNumber("0"), "0");
assert.equal(ui.formatNumber(1250), "1,250");

const broken = ui.normalizeReport({generated_at: fresh, videos: [video(0, "22"), video(0, "1")], public_view_total: 0, weekly_review: {...review, summary: "尚無發布滿7天影片"}}, now);
assert.equal(broken.data_quality.status, "invalid");
assert.equal(broken.videos[0].views, null);
assert.equal(broken.videos[0].published_text, "發布日期未知");
assert.equal(broken.public_view_total, null);
assert.equal(ui.reviewAvailable(broken), false);

const zero = ui.normalizeReport({generated_at: fresh, videos: [video(0)], weekly_review: review}, now);
assert.equal(zero.data_quality.status, "valid");
assert.equal(zero.videos[0].views, 0);
assert.equal(zero.public_view_total, 0);
assert.equal(ui.reviewAvailable(zero), true);
assert.equal(ui.reviewAvailable(ui.normalizeReport({generated_at: fresh, videos: [video(0)]}, now)), false);

const partial = ui.normalizeReport({generated_at: fresh, videos: [video(6), video(null)], weekly_review: review}, now);
assert.equal(partial.data_quality.status, "partial");
assert.equal(partial.public_view_total, null);
assert.equal(ui.seriesSummary(partial.videos)[0].views, null);
assert.equal(ui.reviewAvailable(partial), false);

const stale = ui.normalizeReport({generated_at: "2026-10-14T10:30:00+08:00", last_attempt_at: fresh, videos: [video(8)], weekly_review: review}, now);
assert.equal(stale.data_quality.status, "stale");
assert.equal(stale.videos[0].views, 8);
assert.equal(ui.reviewAvailable(stale), false);

const falselyValid = ui.normalizeReport({generated_at: fresh, data_quality: {status: "valid"}, videos: [video(null)], weekly_review: review}, now);
assert.equal(falselyValid.data_quality.status, "partial");
assert.equal(ui.reviewAvailable(falselyValid), false);
const future = ui.normalizeReport({generated_at: "2026-10-22T10:30:00+08:00", videos: [video(8)], weekly_review: review}, now);
assert.equal(future.data_quality.status, "stale");
const legacyReview = ui.normalizeReport({generated_at: fresh, videos: [video(8)], weekly_review: {...review, status: undefined}}, now);
assert.equal(ui.reviewAvailable(legacyReview), false);

const elements = new Map();
function element() {
  return {textContent: "", className: "", children: [], replaceChildren() {this.children = [];}, append(...items) {this.children.push(...items);}};
}
global.document = {
  querySelector(selector) {if (!elements.has(selector)) elements.set(selector, element()); return elements.get(selector);},
  createElement: element,
};
ui.renderMetrics(broken);
assert.equal(elements.get("#viewTotal").textContent, "—");
assert.equal(elements.get("#topViews").textContent, "—");
assert.equal(elements.get("#videoCount").textContent, "2");
ui.renderMetrics(zero);
assert.equal(elements.get("#viewTotal").textContent, "0");
assert.equal(elements.get("#topViews").textContent, "0");

ui.renderReview(broken);
assert.match(elements.get("#reviewSummary").textContent, /暫停/);
assert.doesNotMatch(elements.get("#reviewSummary").textContent, /尚無發布滿/);
assert.equal(elements.get("#reviewMet").textContent, "—");
assert.equal(elements.get("#strategyList").children.length, 1);
assert.doesNotMatch(elements.get("#strategyList").children[0].textContent, /有效建議/);
ui.renderReview(stale);
assert.equal(elements.get("#reviewMet").textContent, "—");

ui.renderQuality(stale);
assert.match(elements.get("#updatedAt").textContent, /2026\/10\/14/);
assert.match(elements.get("#lastAttempt").textContent, /2026\/10\/20/);
assert.match(elements.get("#dataCoverage").textContent, /不代表頻道全部/);
assert.match(elements.get("#dataSource").textContent, /公開頻道頁/);
ui.renderQuality({...stale, source: "YouTube Data API v3"});
assert.match(elements.get("#dataSource").textContent, /Data API/);

ui.renderOwnerAnalytics({});
assert.equal(elements.get("#ownerAnalyticsStatus").textContent, "尚未連接");
assert.equal(elements.get("#ownerCtr").textContent, "—");
ui.renderOwnerAnalytics({owner_analytics: {status: "reauthorization_required", metrics: {impressions: 999, impressions_ctr_percent: 5}}});
assert.equal(elements.get("#ownerAnalyticsStatus").textContent, "需要授權");
assert.equal(elements.get("#ownerImpressions").textContent, "—");
assert.equal(elements.get("#ownerCtr").textContent, "—");
ui.renderOwnerAnalytics({owner_analytics: {status: "available", metrics: {impressions: 0, impressions_ctr_percent: 0, average_view_duration_seconds: 125}}});
assert.equal(elements.get("#ownerImpressions").textContent, "0");
assert.equal(elements.get("#ownerCtr").textContent, "0%");
assert.equal(elements.get("#ownerAverageDuration").textContent, "125 秒");
assert.equal(elements.get("#ownerRetention").textContent, "—");
console.log("Dashboard regression behavior checks passed");
'''
        result = subprocess.run([shutil.which("node"), "-e", script], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_static_labels_explain_sample_and_cumulative_scope(self) -> None:
        html = (ROOT / "docs/index.html").read_text(encoding="utf-8")
        self.assertIn("本次樣本影片", html)
        self.assertIn("樣本累計觀看", html)
        self.assertIn("上架滿七天的累計觀看觀察", html)
        self.assertIn("無法回推上架首七日表現", html)
        self.assertIn('id="ownerAnalyticsStatus"', html)


if __name__ == "__main__":
    unittest.main()
