/* One renderer for workflow metadata; no workflow IDs or business decisions. */
(function (root) {
  function splitLines(value) {
    return value.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
  }

  function parseValue(type, value) {
    if (type === 'array') return splitLines(value);
    if (type === 'number') {
      if (!value.trim()) return null;
      const n = Number(value);
      if (!Number.isFinite(n) || n < 0) throw Error('Enter a finite nonnegative number');
      return n;
    }
    return value.trim();
  }

  function build(container, guide, values, changed) {
    container.replaceChildren();
    const readers = {}, required = new Set(guide.required_fields || []);
    const alternatives = new Set((guide.required_any || []).flat());
    const primary = document.createElement('div');primary.className = 'form-grid';
    const optional = document.createElement('details');optional.className = 'optional-fields';
    const summary = document.createElement('summary');summary.textContent = 'Optional details';optional.append(summary);
    const extra = document.createElement('div');extra.className = 'form-grid';optional.append(extra);
    let count = 0;
    for (const [name, placeholder] of Object.entries(guide.input_template || {})) {
      const type = (guide.input_types || {})[name] || (placeholder === null ? 'number' : Array.isArray(placeholder) ? 'array' : typeof placeholder === 'object' ? 'object' : 'string');
      const value = values[name] === undefined ? placeholder : values[name];
      const box = document.createElement('div');box.className = 'field';box.dataset.field = name;
      const label = document.createElement('label');label.textContent = name.replace(/_/g, ' ') + (required.has(name) ? ' *' : alternatives.has(name) ? ' (provide one)' : '');
      box.append(label);
      if (type === 'object') {
        box.classList.add('wide');
        const rows = document.createElement('div');box.append(rows);
        function addRow(key = '', terms = []) {
          const row = document.createElement('div');row.className = 'mapping-row';
          const k = document.createElement('input');k.type = 'text';k.placeholder = 'Category name';k.setAttribute('aria-label','Category name');k.value = key;
          const t = document.createElement('input');t.type = 'text';t.placeholder = 'Matching terms, separated by commas';t.setAttribute('aria-label','Matching terms, separated by commas');t.value = terms.join(', ');
          const remove = document.createElement('button');remove.type = 'button';remove.className = 'secondary';remove.textContent = 'Remove';
          remove.onclick = () => { row.remove();changed(); };
          k.oninput = t.oninput = changed;row.append(k,t,remove);rows.append(row);
        }
        const entries = value && typeof value === 'object' && !Array.isArray(value) ? Object.entries(value) : [];
        for (const [k,v] of entries) addRow(k,Array.isArray(v) ? v : []);
        if (!entries.length) addRow();
        const add = document.createElement('button');add.type = 'button';add.className = 'secondary';add.textContent = 'Add category';add.onclick = () => {addRow();changed();};box.append(add);
        readers[name] = () => {
          const out = {};
          for (const row of rows.children) {
            const [k,t] = row.querySelectorAll('input');const key = k.value.trim(), terms = t.value.split(',').map(s=>s.trim()).filter(Boolean);
            if (!key && !terms.length) continue;
            if (!key || !terms.length) throw Error('Each category needs a name and matching terms');
            if (Object.prototype.hasOwnProperty.call(out,key)) throw Error('Category names must be unique');
            Object.defineProperty(out,key,{value:terms,enumerable:true,writable:true,configurable:true});
          }
          return out;
        };
      } else {
        const input = document.createElement(type === 'array' ? 'textarea' : 'input');
        input.id = 'field-' + name;label.htmlFor = input.id;
        if (type !== 'array') {input.type = type === 'number' ? 'number' : 'text';if (type === 'number') {input.min = '0';input.step = 'any';}}
        input.value = type === 'array' ? (Array.isArray(value) ? value.join('\n') : '') : value == null ? '' : String(value);
        input.oninput = changed;box.append(input);
        if (type === 'array') {const note = document.createElement('div');note.className = 'meta';note.textContent = 'Enter one item per line.';box.append(note);}
        readers[name] = () => parseValue(type,input.value);
      }
      const hint = document.createElement('div');hint.className = 'meta';hint.textContent = (guide.input_help || {})[name] || '';box.append(hint);
      if (required.has(name) || alternatives.has(name)) {primary.append(box);count++;} else extra.append(box);
    }
    if (count) container.append(primary);
    else {const note = document.createElement('p');note.className = 'small';note.textContent = 'No required fields. Optional details let you change the sample data or settings.';container.append(note);}
    if (extra.children.length) container.append(optional);
    return () => Object.fromEntries(Object.entries(readers).map(([name,read])=>[name,read()]));
  }

  const api = {build,parseValue};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.InputForms = api;
})(typeof window !== 'undefined' ? window : globalThis);
