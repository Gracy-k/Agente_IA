// Modo de conversa por voz (estilo "Gemini Live").
// Como funciona, em 4 passos:
// 1. O microfone fica ligado; quando o volume passa de um limite, começa a gravar.
// 2. Quando você fica ~1 segundo em silêncio, a gravação é enviada ao servidor.
// 3. O servidor transcreve, pensa (e pesquisa/gera imagem se precisar) e devolve áudio.
// 4. O áudio toca; se você falar por cima, ele para e volta a ouvir (interrupção).
(() => {
  const SPEECH_LEVEL = 0.035; // volume que conta como fala
  const BARGE_IN_LEVEL = 0.07; // volume para interromper a resposta (mais alto, evita eco)
  const SILENCE_MS = 1000; // pausa que encerra a sua fala
  const MIN_SPEECH_MS = 350; // ignora barulhos curtos

  let stream, audioCtx, analyser, recorder, chunks, player;
  let state = "off"; // off | listening | recording | thinking | speaking
  let speechStart = 0, lastLoud = 0, loudSince = 0, raf = null;

  const el = (id) => document.getElementById(id);
  const orb = () => el("liveOrb");

  function setState(next, text) {
    state = next;
    const labels = { listening: "Ouvindo…", recording: "Ouvindo você…", thinking: "Pensando…", speaking: "Falando…" };
    el("liveState").textContent = labels[next] || "";
    orb().className = "live-orb" + (next === "thinking" ? " thinking" : next === "speaking" ? " speaking" : "");
    if (text !== undefined) el("liveText").textContent = text;
  }

  function volume() {
    const data = new Float32Array(analyser.fftSize);
    analyser.getFloatTimeDomainData(data);
    let sum = 0;
    for (const v of data) sum += v * v;
    return Math.sqrt(sum / data.length);
  }

  function loop() {
    if (state === "off") return;
    const level = volume(), now = performance.now();
    orb().style.transform = `scale(${1 + Math.min(level * 6, 0.35)})`;

    if (state === "listening" && level > SPEECH_LEVEL) startRecording(now);
    else if (state === "recording") {
      if (level > SPEECH_LEVEL) lastLoud = now;
      else if (now - lastLoud > SILENCE_MS) stopRecording(now);
    } else if (state === "speaking") {
      // interrupção: fala alta e contínua por 250 ms enquanto a resposta toca
      if (level > BARGE_IN_LEVEL) {
        loudSince = loudSince || now;
        if (now - loudSince > 250) { stopPlayback(); startRecording(now); }
      } else loudSince = 0;
    }
    raf = requestAnimationFrame(loop);
  }

  function startRecording(now) {
    chunks = [];
    recorder = new MediaRecorder(stream);
    recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    recorder.start();
    speechStart = lastLoud = now;
    loudSince = 0;
    setState("recording");
  }

  function stopRecording(now) {
    const longEnough = now - speechStart > MIN_SPEECH_MS + SILENCE_MS;
    recorder.onstop = () => (longEnough ? send(new Blob(chunks, { type: recorder.mimeType })) : setState("listening"));
    recorder.stop();
    setState(longEnough ? "thinking" : "listening");
  }

  function stopPlayback() {
    if (player) { player.pause(); player = null; }
  }

  // Converte a gravação para WAV 16 kHz mono (o formato que o Whisper usa), aqui no navegador.
  async function toWav16k(blob) {
    const decoded = await audioCtx.decodeAudioData(await blob.arrayBuffer());
    const offline = new OfflineAudioContext(1, Math.ceil(decoded.duration * 16000), 16000);
    const source = offline.createBufferSource();
    source.buffer = decoded;
    source.connect(offline.destination);
    source.start();
    const samples = (await offline.startRendering()).getChannelData(0);
    const view = new DataView(new ArrayBuffer(44 + samples.length * 2));
    const text = (o, s) => [...s].forEach((c, i) => view.setUint8(o + i, c.charCodeAt(0)));
    text(0, "RIFF"); view.setUint32(4, 36 + samples.length * 2, true); text(8, "WAVEfmt ");
    view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
    view.setUint32(24, 16000, true); view.setUint32(28, 32000, true); view.setUint16(32, 2, true);
    view.setUint16(34, 16, true); text(36, "data"); view.setUint32(40, samples.length * 2, true);
    samples.forEach((v, i) => view.setInt16(44 + i * 2, Math.max(-1, Math.min(1, v)) * 0x7fff, true));
    return new Blob([view], { type: "audio/wav" });
  }

  async function send(blob) {
    try {
      if (!window.currentChatIdForVoice()) await window.createChatForVoice();
      const form = new FormData();
      form.append("audio", await toWav16k(blob), "fala.wav");
      form.append("chat_id", window.currentChatIdForVoice());
      form.append("model", el("modelSelect").value);
      const response = await fetch("/api/voice", { method: "POST", body: form });
      const data = await response.json();
      if (state === "off") return;
      if (!response.ok) throw new Error(data.error || `Erro HTTP ${response.status}`);
      if (!data.text) return setState("listening", "Não entendi. Pode repetir?");
      window.showVoiceTurn(data);
      setState("speaking", data.answer.split("\n\nFontes:")[0]);
      player = new Audio("data:audio/wav;base64," + data.audio);
      player.onended = () => state === "speaking" && setState("listening");
      await player.play();
    } catch (err) {
      if (state !== "off") setState("listening", "Erro: " + err.message);
    }
  }

  async function start() {
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
    } catch (_) {
      alert("Não foi possível acessar o microfone. Verifique a permissão do navegador.");
      return;
    }
    audioCtx = new AudioContext();
    analyser = audioCtx.createAnalyser();
    analyser.fftSize = 1024;
    audioCtx.createMediaStreamSource(stream).connect(analyser);
    el("liveOverlay").hidden = false;
    setState("listening", "Pode falar. Eu respondo quando você fizer uma pausa.");
    loop();
  }

  function stop() {
    state = "off";
    cancelAnimationFrame(raf);
    stopPlayback();
    if (recorder && recorder.state !== "inactive") recorder.stop();
    stream && stream.getTracks().forEach((t) => t.stop());
    audioCtx && audioCtx.close();
    el("liveOverlay").hidden = true;
  }

  el("voiceBtn").addEventListener("click", start);
  el("liveStop").addEventListener("click", stop);
  document.addEventListener("keydown", (e) => e.key === "Escape" && state !== "off" && stop());
})();
