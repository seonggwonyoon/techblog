"use strict";

const directory = document.querySelector("#directory");
const form = document.querySelector("#filters");
const query = document.querySelector("#query");
const topics = [...directory.querySelectorAll('[name="topic"]')];
const download = document.querySelector("#download-feeds");
const resetButton = document.querySelector("#reset");
const topicPicker = directory.querySelector(".topic-picker");
const foldedGroups = [...directory.querySelectorAll(".blog-group")];
const narrowScreen = window.matchMedia("(max-width: 760px)");

function normalize(text) {
  return text.normalize("NFKC").toLowerCase();
}

const blogs = [...directory.querySelectorAll(".entry")].map((row) => {
  const link = row.querySelector(".blog-name");
  const feed = row.querySelector(".feed-link");
  const tags = [...row.querySelectorAll(".tag")].map((tag) => tag.textContent);
  const words = [link.textContent, row.dataset.aliases, link.hostname, ...tags];
  return {
    row, link, feed, tags,
    region: row.dataset.region,
    archive: row.hasAttribute("data-archive"),
    quiet: row.hasAttribute("data-quiet"),
    search: normalize(words.join(" ")),
  };
});
const feedTotal = blogs.filter((blog) => blog.feed).length;
let selectionUrl = null;

function renderOpml(feeds) {
  const xml = document.implementation.createDocument(null, "opml");
  const root = xml.documentElement;
  root.setAttribute("version", "2.0");
  const head = xml.createElement("head");
  const title = xml.createElement("title");
  title.textContent = "techblog 구독 목록";
  head.append(title);
  const body = xml.createElement("body");
  root.append(head, body);

  const groups = new Map();
  for (const blog of feeds) {
    if (!groups.has(blog.region)) {
      const group = xml.createElement("outline");
      group.setAttribute("text", blog.region);
      body.append(group);
      groups.set(blog.region, group);
    }
    const outline = xml.createElement("outline");
    outline.setAttribute("type", "rss");
    outline.setAttribute("text", blog.link.textContent);
    outline.setAttribute("title", blog.link.textContent);
    outline.setAttribute("htmlUrl", blog.link.href);
    outline.setAttribute("xmlUrl", blog.feed.href);
    groups.get(blog.region).append(outline);
  }
  return new XMLSerializer().serializeToString(xml);
}

function updateDownload(feeds) {
  if (selectionUrl) {
    URL.revokeObjectURL(selectionUrl);
    selectionUrl = null;
  }
  const summary = document.querySelector("#feed-summary");
  if (feeds.length === 0) {
    summary.textContent = "현재 목록에 구독할 피드가 없습니다";
    download.removeAttribute("href");
    download.setAttribute("aria-disabled", "true");
    return;
  }
  summary.textContent = "현재 목록의 피드 " + feeds.length + "개";
  download.removeAttribute("aria-disabled");
  const complete = feeds.length === feedTotal;
  download.download = complete ? "techblog-feeds.opml" : "techblog-selection.opml";
  // A sibling file can open as a document instead of a download on file://.
  if (complete && window.location.protocol !== "file:") {
    download.href = "feeds.opml";
  } else {
    const file = new Blob([renderOpml(feeds)], { type: "application/xml;charset=utf-8" });
    selectionUrl = URL.createObjectURL(file);
    download.href = selectionUrl;
  }
}

function filterBlogs() {
  const terms = normalize(query.value.trim()).split(/\s+/).filter(Boolean);
  const scope = form.elements.scope.value;
  const topic = form.elements.topic.value;
  const feedOnly = document.querySelector("#with-feed").checked;
  const filtering = terms.length > 0 || scope !== "all" || topic !== "" || feedOnly;
  const counts = new Map();
  const feeds = [];
  let visible = 0;
  let baseCount = 0;
  for (const blog of blogs) {
    const inScope = scope === "all" || scope === blog.region
      || (scope === "archive" && blog.archive) || (scope === "quiet" && blog.quiet);
    const matches = inScope && (!feedOnly || blog.feed) && terms.every((term) => blog.search.includes(term));
    if (matches) {
      baseCount++;
      for (const tag of blog.tags) counts.set(tag, (counts.get(tag) || 0) + 1);
    }
    blog.row.hidden = !matches || (topic !== "" && !blog.tags.includes(topic));
    if (!blog.row.hidden) {
      visible++;
      if (blog.feed) feeds.push(blog);
    }
  }
  for (const control of topics) {
    control.labels[0].querySelector("small").textContent = control.value ? counts.get(control.value) || 0 : baseCount;
  }
  for (const group of foldedGroups) {
    const count = group.querySelectorAll(".entry:not([hidden])").length;
    group.hidden = count === 0;
    group.open = filtering && count > 0;
    group.querySelector(".group-count").textContent = count + "곳";
  }
  document.querySelector("#current-topic").textContent = topic || "전체 주제";
  document.querySelector("#result-count").textContent = "블로그 " + visible + "곳";
  directory.querySelector(".empty-state").hidden = visible !== 0;
  resetButton.hidden = !filtering;
  updateDownload(feeds);
}

function resetFilters() {
  form.reset();
  filterBlogs();
  query.focus();
}

function sizeTopicPicker() {
  topicPicker.open = !narrowScreen.matches;
}

function closeTopicPicker() {
  topicPicker.open = false;
  topicPicker.querySelector("summary").focus({ preventScroll: true });
}

sizeTopicPicker();
narrowScreen.addEventListener("change", sizeTopicPicker);
form.addEventListener("submit", (event) => event.preventDefault());
directory.addEventListener("input", filterBlogs);
topicPicker.addEventListener("click", (event) => {
  if (narrowScreen.matches && event.target.name === "topic" && event.detail > 0) {
    closeTopicPicker();
  }
});
topicPicker.addEventListener("keydown", (event) => {
  if (narrowScreen.matches && event.target.name === "topic" && ["Enter", "Escape"].includes(event.key)) {
    event.preventDefault();
    closeTopicPicker();
  }
});
resetButton.addEventListener("click", resetFilters);
document.querySelector("#show-all").addEventListener("click", resetFilters);
window.addEventListener("pageshow", filterBlogs);
filterBlogs();
document.documentElement.classList.add("enhanced");

if ("IntersectionObserver" in window) {
  const topLink = document.querySelector(".back-to-top");
  topLink.hidden = true;
  topLink.classList.add("floating");
  const observer = new IntersectionObserver(([entry]) => {
    topLink.hidden = entry.isIntersecting || entry.boundingClientRect.bottom > 0;
  });
  observer.observe(document.querySelector(".intro"));
}
