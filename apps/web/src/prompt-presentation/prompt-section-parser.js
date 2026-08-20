const SECTION_TITLES = {
  "复刻要求": "replication",
  "基础画面": "visual",
  "时间轴": "timeline",
  "出场转场": "transition",
  "约束": "constraints",
  "约束与补充说明": "constraints",
  "补充说明": "notes",
};

const VISUAL_LABELS = ["主体", "场景", "构图", "光线", "色彩"];
const TIMELINE_LABELS = ["主体", "镜头", "前景", "焦点", "动作过程", "运镜"];
const TRANSITION_LABELS = ["转场方式", "动作过程", "运镜", "遮挡对象", "运动方向", "结束状态"];
const SECTION_PATTERN = /【\s*(复刻要求|基础画面|时间轴|出场转场|约束与补充说明|约束|补充说明)\s*】/g;
const TIME_RANGE_PATTERN = /(\d+(?:\.\d+)?)\s*[–—-]\s*(\d+(?:\.\d+)?)\s*(?:s|秒)/g;

function cleanText(value) {
  return String(value || "")
    .replace(/\r\n?/g, "\n")
    .replace(/[\t ]+/g, " ")
    .replace(/ *\n */g, "\n")
    .trim();
}

function splitParagraphs(value) {
  const text = cleanText(value);
  if (!text) return [];
  return text
    .split(/\n{2,}|\n(?=[^-•·])/)
    .map((item) => item.replace(/^[-•·]\s*/, "").trim())
    .filter(Boolean);
}

function parseFields(value, labels) {
  const text = cleanText(value);
  if (!text) return { lead: [], fields: [] };
  const labelPattern = new RegExp(`(?:^|\\s)(${labels.join("|")})\\s*[：:]\\s*`, "g");
  const matches = [...text.matchAll(labelPattern)];
  if (!matches.length) return { lead: splitParagraphs(text), fields: [] };

  const leadText = text.slice(0, matches[0].index).trim();
  const fields = matches.map((match, index) => {
    const start = match.index + match[0].length;
    const end = matches[index + 1]?.index ?? text.length;
    return {
      label: match[1],
      value: text.slice(start, end).trim().replace(/[；;]\s*$/, ""),
    };
  }).filter((item) => item.value);
  return { lead: splitParagraphs(leadText), fields };
}

function parseTimeline(value) {
  const text = cleanText(value);
  const matches = [...text.matchAll(TIME_RANGE_PATTERN)];
  if (!matches.length) return [];
  return matches.map((match, index) => {
    const start = match.index + match[0].length;
    const end = matches[index + 1]?.index ?? text.length;
    const content = text.slice(start, end).trim().replace(/^[｜|·：:]\s*/, "");
    const parsed = parseFields(content, TIMELINE_LABELS);
    return {
      time: `${match[1]}–${match[2]}s`,
      lead: parsed.lead,
      fields: parsed.fields,
    };
  });
}

function makeSection(title, content) {
  const key = SECTION_TITLES[title] || "notes";
  if (key === "visual") return { key, title, ...parseFields(content, VISUAL_LABELS) };
  if (key === "timeline") {
    const segments = parseTimeline(content);
    return segments.length
      ? { key, title, segments }
      : { key, title, segments: [], paragraphs: splitParagraphs(content) };
  }
  if (key === "transition") return { key, title, ...parseFields(content, TRANSITION_LABELS) };
  return { key, title, paragraphs: splitParagraphs(content) };
}

export function parsePromptSections(value) {
  const text = cleanText(value);
  if (!text) return { intro: [], sections: [] };
  const matches = [...text.matchAll(SECTION_PATTERN)];
  if (!matches.length) return { intro: splitParagraphs(text), sections: [] };

  const intro = splitParagraphs(text.slice(0, matches[0].index));
  const sections = matches.map((match, index) => {
    const start = match.index + match[0].length;
    const end = matches[index + 1]?.index ?? text.length;
    return makeSection(match[1], text.slice(start, end));
  }).filter((section) => (
    section.paragraphs?.length
    || section.lead?.length
    || section.fields?.length
    || section.segments?.length
  ));
  return { intro, sections };
}
