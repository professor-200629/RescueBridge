// Browser speech: recognition (may use an online service, browser-dependent) and synthesis.
// Cancelling speech output never affects repair permission; that is what Stop is for.

type RecState = "idle" | "listening" | "unsupported" | "error";

export interface VoiceCallbacks {
  onTranscript(text: string, final: boolean): void;
  onState(state: RecState, detail?: string): void;
  onSpeaking(speaking: boolean): void;
}

export class Voice {
  private rec: any = null;
  private listening = false;
  readonly recognitionSupported: boolean;
  readonly synthesisSupported: boolean;

  constructor(private cb: VoiceCallbacks) {
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    this.recognitionSupported = Boolean(SR) && window.isSecureContext;
    this.synthesisSupported = "speechSynthesis" in window;
    if (this.recognitionSupported) {
      this.rec = new SR();
      this.rec.lang = navigator.language || "en-IN";
      this.rec.interimResults = true;
      this.rec.continuous = false;
      this.rec.maxAlternatives = 1;
      this.rec.onresult = (ev: any) => {
        let text = "";
        let final = false;
        for (let i = 0; i < ev.results.length; i++) {
          text += ev.results[i][0].transcript;
          if (ev.results[i].isFinal) final = true;
        }
        this.cb.onTranscript(text.trim(), final);
      };
      this.rec.onerror = (ev: any) => {
        this.listening = false;
        const msg: Record<string, string> = {
          "not-allowed": "Microphone permission was denied. Allow it in the browser's site settings, or type instead.",
          "service-not-allowed": "Speech recognition is not allowed here. Type instead.",
          "no-speech": "I didn't hear anything. Try again or type.",
          network: "Speech recognition needs a network service in this browser and it failed. Type instead.",
          "audio-capture": "No microphone was found. Type instead.",
        };
        this.cb.onState("error", msg[ev.error] ?? `Speech recognition error: ${ev.error}`);
      };
      this.rec.onend = () => {
        if (this.listening) {
          this.listening = false;
          this.cb.onState("idle");
        }
      };
    }
  }

  start(): void {
    if (!this.rec) {
      this.cb.onState("unsupported", "Voice input is not available in this browser/context. Type instead.");
      return;
    }
    this.stopSpeaking();
    try {
      this.rec.start();
      this.listening = true;
      this.cb.onState("listening");
    } catch {
      this.cb.onState("error", "Could not start listening. Try again.");
    }
  }

  stopListening(): void {
    if (this.rec && this.listening) this.rec.stop();
  }

  get isListening(): boolean {
    return this.listening;
  }

  speak(text: string): void {
    if (!this.synthesisSupported || !text) return;
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.lang = navigator.language || "en-IN";
    u.rate = 1.0;
    u.onstart = () => this.cb.onSpeaking(true);
    u.onend = () => this.cb.onSpeaking(false);
    u.onerror = () => this.cb.onSpeaking(false);
    window.speechSynthesis.speak(u);
  }

  stopSpeaking(): void {
    if (this.synthesisSupported) window.speechSynthesis.cancel();
    this.cb.onSpeaking(false);
  }
}
