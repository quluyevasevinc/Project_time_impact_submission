/*
 * Smoke test for the dashboard's rendering code.
 *
 * The page's draw functions touch the DOM, so they cannot run under a plain
 * JavaScript engine. This file provides the small amount of DOM the page
 * actually uses — enough to execute every tab, for every quarter, under both
 * measures, and fail loudly on a thrown error or an unrendered value.
 *
 * It is not a substitute for looking at the page. It catches the class of
 * break that is easy to ship and tedious to spot: a renamed payload field, a
 * typo in a draw function, a tab that throws only when a particular filter is
 * selected.
 *
 * `run_render_tests.py` assembles this with the page's own scripts.
 */

// --- minimal DOM ----------------------------------------------------------

function Node(tag) {
  this.tagName = (tag || "").toUpperCase();
  this.childNodes = [];
  this.className = "";
  this.style = {};
  this.dataset = {};
  this._text = "";
  this.title = "";
}

Object.defineProperty(Node.prototype, "textContent", {
  get: function () {
    if (this.childNodes.length === 0) return this._text;
    return this.childNodes.map(function (c) { return c.textContent; }).join("");
  },
  set: function (v) { this._text = String(v); this.childNodes = []; }
});

Object.defineProperty(Node.prototype, "firstChild", {
  get: function () { return this.childNodes[0] || null; }
});

Object.defineProperty(Node.prototype, "cells", {
  get: function () { return this.childNodes.slice(); }
});

Object.defineProperty(Node.prototype, "parentNode", {
  get: function () { return this._parent || null; }
});

Node.prototype.appendChild = function (child) {
  child._parent = this;
  this.childNodes.push(child);
  return child;
};

Node.prototype.removeChild = function (child) {
  var i = this.childNodes.indexOf(child);
  if (i >= 0) this.childNodes.splice(i, 1);
  return child;
};

Node.prototype.insertBefore = function (child, ref) {
  var i = this.childNodes.indexOf(ref);
  child._parent = this;
  this.childNodes.splice(i < 0 ? this.childNodes.length : i, 0, child);
  return child;
};

Node.prototype.setAttribute = function (k, v) { this["attr_" + k] = v; };
Node.prototype.getAttribute = function (k) { return this["attr_" + k]; };
Node.prototype.removeAttribute = function (k) { delete this["attr_" + k]; };
Node.prototype.addEventListener = function () {};

Object.defineProperty(Node.prototype, "innerHTML", {
  get: function () { return this._html || this.textContent; },
  set: function (v) { this._html = String(v); this.childNodes = []; this._text = ""; }
});

function walk(node, out) {
  out.push(node);
  node.childNodes.forEach(function (c) { walk(c, out); });
  return out;
}

function matches(node, selector) {
  // Supports the selector shapes the page actually uses.
  var m = selector.match(/^#([\w-]+)$/);
  if (m) return node.id === m[1];
  m = selector.match(/^([a-zA-Z]+)?\.([\w-]+)$/);
  if (m) {
    var tagOk = !m[1] || node.tagName === m[1].toUpperCase();
    return tagOk && (" " + node.className + " ").indexOf(" " + m[2] + " ") >= 0;
  }
  m = selector.match(/^([a-zA-Z]+)$/);
  if (m) return node.tagName === m[1].toUpperCase();
  m = selector.match(/\[data-tab="([\w-]+)"\]/);
  if (m) return node.dataset.tab === m[1];
  return false;
}

function descend(root, selector) {
  var parts = selector.trim().split(/\s+/);
  var last = parts[parts.length - 1];
  return walk(root, []).filter(function (n) { return matches(n, last); });
}

var registry = {};

function TextNode(text) {
  Node.call(this, "#text");
  this._text = String(text);
}
TextNode.prototype = Object.create(Node.prototype);

var document = {
  _root: new Node("body"),
  createElement: function (tag) { return new Node(tag); },
  createElementNS: function (ns, tag) { return new Node(tag); },
  createTextNode: function (text) { return new TextNode(text); },
  getElementById: function (id) { return registry[id] || null; },
  querySelector: function (s) { return descend(document._root, s)[0] || null; },
  querySelectorAll: function (s) { return descend(document._root, s); },
  documentElement: new Node("html"),
  body: null
};
document.body = document._root;

var window = {
  matchMedia: function () { return { matches: false }; }
};

// Every id the page declares, scraped from the built HTML by
// run_render_tests.py. Taken from the page rather than listed here, so adding
// a card to the template cannot leave the stub silently behind.
ELEMENT_IDS.forEach(function (id) {
  var n = new Node("div");
  n.id = id;
  registry[id] = n;
  document._root.appendChild(n);
});

// Tab buttons, so the wiring code finds something to bind to.
var nav = new Node("nav");
nav.className = "tabs";
document._root.appendChild(nav);
["overview", "time", "people", "impact", "projects", "health"].forEach(function (t) {
  var b = new Node("button");
  b.dataset.tab = t;
  nav.appendChild(b);
});

// The payload is substituted in by run_render_tests.py.
registry.payload._text = PAYLOAD_JSON;

/** Empty every host the page draws into, so each render is checked alone. */
function resetHosts() {
  Object.keys(registry).forEach(function (id) {
    if (id === "payload") return;
    var n = registry[id];
    n.childNodes = [];
    n._text = "";
    n._html = "";
  });
}
