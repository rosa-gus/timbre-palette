const categories = new Set(["zero", "one", "two", "few", "many", "other"]);

/** Parse named arguments and cardinal ICU plurals; values are never parsed. */
export function parseMessage(text) {
  let position = 0;
  const fail = () => { throw new Error(`Malformed message near position ${position}`); };
  const space = () => { while (/\s/.test(text[position] ?? "") && position < text.length) position++; };
  const word = () => {
    space();
    const match = /^[A-Za-z][A-Za-z0-9_]*/.exec(text.slice(position));
    if (!match) fail();
    position += match[0].length;
    return match[0];
  };
  function sequence(nested = false, count) {
    const nodes = [];
    let literal = "";
    const flush = () => { if (literal) nodes.push({ type: "text", value: literal }); literal = ""; };
    while (position < text.length) {
      const char = text[position++];
      if (char === "}") {
        if (!nested) fail();
        flush(); return nodes;
      }
      if (char === "#" && count) {
        flush(); nodes.push({ type: "argument", name: count }); continue;
      }
      if (char !== "{") { literal += char; continue; }
      flush();
      const name = word(); space();
      if (text[position] === "}") {
        position++; nodes.push({ type: "argument", name }); continue;
      }
      if (text[position++] !== "," || word() !== "plural") fail();
      space(); if (text[position++] !== ",") fail();
      const options = Object.create(null);
      while (true) {
        space();
        if (text[position] === "}") { position++; break; }
        const exact = /^=\d+/.exec(text.slice(position));
        const category = exact ? (position += exact[0].length, exact[0]) : word();
        if ((!exact && !categories.has(category)) || Object.hasOwn(options, category)) fail();
        space(); if (text[position++] !== "{") fail();
        options[category] = sequence(true, name);
      }
      if (!Object.hasOwn(options, "other")) fail();
      nodes.push({ type: "plural", name, options });
    }
    if (nested) fail();
    flush(); return nodes;
  }
  return sequence();
}

export function analyzeMessage(text) {
  const parameters = new Set(), plurals = new Set();
  function variants(nodes) {
    let result = [""];
    for (const node of nodes) {
      let choices;
      if (node.type === "text") choices = [node.value];
      else {
        parameters.add(node.name);
        if (node.type === "argument") choices = [`{${node.name}}`];
        else {
          plurals.add(node.name);
          choices = Object.values(node.options).flatMap(variants);
        }
      }
      result = result.flatMap((prefix) => choices.map((choice) => prefix + choice));
      if (result.length > 256) throw new Error("Too many plural combinations in message");
    }
    return result;
  }
  const expanded = variants(parseMessage(text));
  return { parameters: [...parameters].sort(), plurals: [...plurals].sort(), variants: expanded };
}

/** Select authored branches before interpolation or component markup processing. */
export function selectMessage(text, values = {}, language, numberLocale = language) {
  const formatted = { ...values };
  function select(nodes) {
    return nodes.map((node) => {
      if (node.type === "text") return node.value;
      if (node.type === "argument") return `{${node.name}}`;
      const count = values[node.name];
      if (typeof count !== "number" || !Number.isFinite(count))
        throw new Error(`Plural parameter must be a finite number: ${node.name}`);
      formatted[node.name] = new Intl.NumberFormat(numberLocale).format(count);
      const category = new Intl.PluralRules(language).select(count);
      return select(node.options[`=${count}`] ?? node.options[category] ?? node.options.other);
    }).join("");
  }
  return { text: select(parseMessage(text)), values: formatted };
}
