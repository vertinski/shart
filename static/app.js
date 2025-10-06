// Client-side upload logic
const token = window.__TOKEN__;
const picker = document.getElementById('picker');
const drop = document.getElementById('drop');
const send = document.getElementById('send');
const statusEl = document.getElementById('status');
const resultEl = document.getElementById('result');

function setBusy(isBusy) {
  send.disabled = isBusy;
  statusEl.textContent = isBusy ? 'Uploading…' : '';
}

function onFiles(files) {
  picker.files = files;
}

drop.addEventListener('dragover', (e) => { e.preventDefault(); drop.classList.add('drag'); });
drop.addEventListener('dragleave', () => drop.classList.remove('drag'));
drop.addEventListener('drop', (e) => {
  e.preventDefault();
  drop.classList.remove('drag');
  const files = e.dataTransfer.files;
  onFiles(files);
});

send.addEventListener('click', async () => {
  if (!picker.files || picker.files.length === 0) {
    alert('Please choose at least one file.');
    return;
  }
  const form = new FormData();
  for (const f of picker.files) form.append('files', f, f.name);
  setBusy(true);
  try {
    const res = await fetch(`/api/upload/${token}`, { method: 'POST', body: form });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Upload failed');
    resultEl.innerHTML = `<p class="ok">Uploaded:</p><ul>` + data.saved.map(n => `<li>${n}</li>`).join('') + `</ul>`;
  } catch (err) {
    resultEl.innerHTML = `<p class="err">${err.message}</p>`;
  } finally {
    setBusy(false);
  }
});


