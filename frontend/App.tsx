import { StatusBar } from "expo-status-bar";
import { Audio } from "expo-av";
import * as DocumentPicker from "expo-document-picker";
import React, { useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Image,
  Modal,
  Pressable,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
  Linking,
  Share,
  useWindowDimensions,
} from "react-native";
import { colors, spacing } from "./src/theme";

type Tab = "Home" | "Library" | "Focus" | "Questions" | "AI Studio" | "AI Video" | "Payments" | "Settings";
type LearningStyle = "whiteboard" | "cinematic" | "infographic";
type Scene = {
  title: string;
  subtitle: string;
  detail: string;
  visualPrompt: string;
};
type SlideshowScene = {
  heading: string;
  narration: string;
  visual_prompt: string;
  image_url: string;
  recall_question?: string;
  recall_choices?: string[];
  recall_answer_index?: number;
};
type StudentSlideshow = {
  job_id: string;
  title: string;
  summary: string;
  visual_style: LearningStyle;
  audio_url: string;
  scenes: SlideshowScene[];
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isStudentSlideshowPayload(
  payload: unknown,
): payload is Omit<StudentSlideshow, "visual_style"> {
  if (
    !isRecord(payload) ||
    typeof payload.job_id !== "string" ||
    typeof payload.title !== "string" ||
    typeof payload.summary !== "string" ||
    typeof payload.audio_url !== "string" ||
    !Array.isArray(payload.scenes) ||
    payload.scenes.length < 5 ||
    payload.scenes.length > 10
  ) {
    return false;
  }
  return payload.scenes.every(
    (scene) =>
      isRecord(scene) &&
      typeof scene.heading === "string" &&
      typeof scene.narration === "string" &&
      typeof scene.visual_prompt === "string" &&
      typeof scene.image_url === "string",
  );
}

const narrationLanguages = [
  { code: "en", label: "English" }, { code: "es", label: "Spanish" },
  { code: "fr", label: "French" }, { code: "de", label: "German" },
  { code: "it", label: "Italian" }, { code: "pt", label: "Portuguese" },
  { code: "ru", label: "Russian" }, { code: "ja", label: "Japanese" },
  { code: "zh-CN", label: "Chinese" }, { code: "ko", label: "Korean" },
  { code: "ar", label: "Arabic" }, { code: "hi", label: "Hindi" },
  { code: "nl", label: "Dutch" }, { code: "tr", label: "Turkish" },
  { code: "pl", label: "Polish" }, { code: "sv", label: "Swedish" },
  { code: "no", label: "Norwegian" }, { code: "da", label: "Danish" },
  { code: "fi", label: "Finnish" }, { code: "el", label: "Greek" },
  { code: "th", label: "Thai" }, { code: "vi", label: "Vietnamese" },
  { code: "id", label: "Indonesian" }, { code: "tl", label: "Filipino" },
  { code: "he", label: "Hebrew" }, { code: "af", label: "Afrikaans" },
  { code: "bn", label: "Bengali" },
];

const learningStyles: Array<{
  key: LearningStyle;
  icon: string;
  title: string;
  bestFor: string;
  description: string;
}> = [
  {
    key: "whiteboard",
    icon: "🎨",
    title: "2D Whiteboard",
    bestFor: "Abstract ideas · quick reviews · processes",
    description: "Hand-drawn diagrams and clear, color-coded steps.",
  },
  {
    key: "cinematic",
    icon: "🎬",
    title: "Realistic Cinematic",
    bestFor: "Microscopic ideas · history · procedures",
    description: "Immersive, realistic scenes that bring concepts to life.",
  },
  {
    key: "infographic",
    icon: "📊",
    title: "Kinetic Infographics",
    bestFor: "Data · economics · coding and logic",
    description: "Animated charts, visual comparisons, and flowing diagrams.",
  },
];

const motivations = [
  "Consistency beats intelligence. Keep reading! 📚",
  "Every translation makes you a global thinker. 🌍",
];
const recallQuestions = [
  "Can you recall the core analogy of that last video scene?",
  "Try translating your last sentence back to its original language from memory!",
];

// Replace the address with the LAN URL printed by `python main.py`.
const API_BASE_URL = "http://192.168.137.150:8000";

const tabs: Array<{ key: Tab; label: string; icon: string }> = [
  { key: "Home", label: "Home", icon: "⌂" },
  { key: "Library", label: "Library", icon: "▤" },
  { key: "Focus", label: "Focus", icon: "✦" },
  { key: "Questions", label: "Practice", icon: "?" },
  { key: "AI Studio", label: "AI", icon: "✧" },
  { key: "AI Video", label: "Video", icon: "▶" },
  { key: "Payments", label: "Pay", icon: "◈" },
  { key: "Settings", label: "Profile", icon: "⚙" },
];

function SectionTitle({ eyebrow, title }: { eyebrow: string; title: string }) {
  return (
    <View style={styles.sectionTitle}>
      <Text style={styles.eyebrow}>{eyebrow.toUpperCase()}</Text>
      <Text style={styles.sectionHeading}>{title}</Text>
    </View>
  );
}

function PromptField({
  label,
  value,
  onChangeText,
}: {
  label: string;
  value: string;
  onChangeText: (value: string) => void;
}) {
  return (
    <View style={styles.promptField}>
      <Text style={styles.promptLabel}>{label}</Text>
      <TextInput
        style={styles.promptInput}
        value={value}
        onChangeText={onChangeText}
        placeholderTextColor={colors.muted}
        multiline
      />
    </View>
  );
}

function LoginScreen({ onUnlock }: { onUnlock: (sandboxMode: boolean, email: string) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  const submit = () => {
    if (!email.trim() || !email.includes("@") || password.length < 8) {
      setError("Enter a valid email and a password of at least 8 characters.");
      return;
    }
    onUnlock(false, email.trim());
  };

  return (
    <ScrollView contentContainerStyle={styles.loginContent}>
      <Text style={styles.loginMark}>LETSRD</Text>
      <Text style={styles.loginTitle}>Learn anything, clearly.</Text>
      <Text style={styles.pageIntro}>Sign in to sync translations, notes, and visual explanations.</Text>
      <View style={styles.loginCard}>
        <TextInput
          style={styles.loginInput}
          value={email}
          onChangeText={setEmail}
          placeholder="Email"
          placeholderTextColor={colors.muted}
          keyboardType="email-address"
          autoCapitalize="none"
        />
        <TextInput
          style={styles.loginInput}
          value={password}
          onChangeText={setPassword}
          placeholder="Password (8+ characters)"
          placeholderTextColor={colors.muted}
          secureTextEntry
        />
        <Pressable style={styles.primaryButtonWide} onPress={submit}>
          <Text style={styles.primaryButtonText}>Sign in</Text>
        </Pressable>
        <Pressable style={styles.googleButton} onPress={() => onUnlock(false, "google-user@letsrd.local")}>
          <Text style={styles.googleButtonText}>Continue with Google Identity 👑</Text>
        </Pressable>
        <Pressable onPress={() => onUnlock(true, "sandbox@letsrd.local")}>
          <Text style={styles.sandboxLink}>🔧 Developer Sandbox Bypass</Text>
        </Pressable>
        {error ? <Text style={styles.errorText}>{error}</Text> : null}
      </View>
    </ScrollView>
  );
}

function ProgressRing({ progress }: { progress: number }) {
  return (
    <View style={styles.progressRing}>
      <Text style={styles.progressValue}>{progress}%</Text>
      <Text style={styles.progressCaption}>this week</Text>
    </View>
  );
}

function HomeScreen({ onNavigate }: { onNavigate: (tab: Tab) => void }) {
  const [motivation] = useState(() => motivations[Math.floor(Math.random() * motivations.length)]);
  const [recall] = useState(() => recallQuestions[Math.floor(Math.random() * recallQuestions.length)]);
  return (
    <ScrollView contentContainerStyle={styles.content}>
      <View style={styles.headerRow}>
        <View>
          <Text style={styles.greeting}>Good afternoon, Alex</Text>
          <Text style={styles.headerSubtext}>Ready for a little progress?</Text>
        </View>
        <View style={styles.avatar}>
          <Text style={styles.avatarText}>A</Text>
        </View>
      </View>

      <View style={styles.heroCard}>
        <View style={styles.heroCopy}>
          <Text style={styles.heroKicker}>YOUR NEXT STEP</Text>
          <Text style={styles.heroTitle}>Keep your learning rhythm.</Text>
          <Text style={styles.heroBody}>
            A short focus warm-up makes your study time count.
          </Text>
          <Pressable style={styles.primaryButton} onPress={() => onNavigate("Focus")}>
            <Text style={styles.primaryButtonText}>Start focus warm-up</Text>
          </Pressable>
        </View>
        <Text style={styles.heroSpark}>✦</Text>
      </View>

      <View style={styles.statsRow}>
        <View style={styles.statCard}>
          <Text style={styles.statNumber}>4</Text>
          <Text style={styles.statLabel}>day streak</Text>
        </View>
        <View style={styles.statCard}>
          <Text style={styles.statNumber}>32</Text>
          <Text style={styles.statLabel}>min listened</Text>
        </View>
        <View style={styles.statCard}>
          <Text style={styles.statNumber}>8</Text>
          <Text style={styles.statLabel}>questions done</Text>
        </View>
      </View>

      <View style={styles.sectionRow}>
        <SectionTitle eyebrow="Continue learning" title="Your study shelf" />
        <Pressable onPress={() => onNavigate("Library")}>
          <Text style={styles.linkText}>See all</Text>
        </Pressable>
      </View>
      <Pressable style={styles.lessonCard} onPress={() => onNavigate("Library")}>
        <View style={styles.lessonIcon}><Text>PDF</Text></View>
        <View style={styles.lessonDetails}>
          <Text style={styles.lessonTitle}>Computer Organisation</Text>
          <Text style={styles.lessonMeta}>Chapter 3 · 12 min left</Text>
          <View style={styles.progressTrack}><View style={[styles.progressFill, { width: "64%" }]} /></View>
        </View>
        <Text style={styles.chevron}>›</Text>
      </Pressable>

      <View style={styles.sectionRow}>
        <SectionTitle eyebrow="Build confidence" title="A quick practice set" />
        <Pressable onPress={() => onNavigate("Questions")}>
          <Text style={styles.linkText}>Practice</Text>
        </Pressable>
      </View>
      <Pressable style={styles.questionCard} onPress={() => onNavigate("Questions")}>
        <View style={styles.questionBadge}><Text style={styles.questionBadgeText}>3</Text></View>
        <View style={styles.lessonDetails}>
          <Text style={styles.lessonTitle}>Questions from your last test</Text>
          <Text style={styles.lessonMeta}>Creative recall · 5 minutes</Text>
        </View>
        <Text style={styles.chevron}>›</Text>
      </Pressable>
      <View style={styles.motivationCard}>
        <Text style={styles.motivationText}>{motivation}</Text>
        <Text style={styles.lessonMeta}>{recall}</Text>
      </View>
    </ScrollView>
  );
}

function VideoWorkspaceScreen({
  readerText,
  onReaderTextChange,
  accountTier,
  userId,
}: {
  readerText: string;
  onReaderTextChange: (text: string) => void;
  accountTier: "free" | "premium_trial" | "premium_paid";
  userId: string;
}) {
  const defaultScenes: Scene[] = [
    {
      title: "Scene 1 · Darkness and disorder",
      subtitle: "The story begins with darkness and disorder. We first notice the difficult idea.",
      detail: "Look at the starting context before drawing a path.",
      visualPrompt: "",
    },
    {
      title: "Scene 2 · Light reveals a path",
      subtitle: "Light arrives first. A clean line shows how the pieces connect.",
      detail: "One visible action turns the abstract idea into something familiar.",
      visualPrompt: "",
    },
    {
      title: "Scene 3 · The concept becomes clear",
      subtitle: "The finished path makes the difficult concept easy to remember.",
      detail: "Review the whole journey, then explain it in your own words.",
      visualPrompt: "",
    },
  ];
  const [subjectAndCast, setSubjectAndCast] = useState(
    "Maya, a 20-year-old student with warm brown skin, short natural black hair, round glasses, a teal cardigan, white shirt, and dark trousers. Keep her age, face, hair, clothing, and proportions identical in every scene.",
  );
  const [actionGuidance, setActionGuidance] = useState(
    "Give each scene exactly one simple physical movement with a clearly described starting position and ending position.",
  );
  const [cameraMovement, setCameraMovement] = useState(
    "One stable medium shot with a gentle, smooth push-in; no cuts or shake.",
  );
  const [lightingEnvironment, setLightingEnvironment] = useState(
    "A single warm desk-lamp source in a quiet study room at evening; calm, focused mood.",
  );
  const [constraints, setConstraints] = useState(
    "Clean rendering, no garbled text, no floating artifacts, consistent anatomy, smooth motion, no extra limbs.",
  );
  const [scenes, setScenes] = useState<Scene[]>(defaultScenes);
  const [activeScene, setActiveScene] = useState(0);
  const [touring, setTouring] = useState(false);
  const [narrating, setNarrating] = useState(false);
  const [narrationError, setNarrationError] = useState("");
  const [generating, setGenerating] = useState(false);
  const [generationError, setGenerationError] = useState("");
  const [slideshow, setSlideshow] = useState<StudentSlideshow | null>(null);
  const [learningStyle, setLearningStyle] = useState<LearningStyle>("whiteboard");
  const [narrationLanguage, setNarrationLanguage] = useState("en");
  const [audioTextMode, setAudioTextMode] = useState(false);
  const [dualScreen, setDualScreen] = useState(false);
  const [showSubtitles, setShowSubtitles] = useState(true);
  const [zoomVisible, setZoomVisible] = useState(false);
  const [styleImages, setStyleImages] = useState<Record<string, string>>({});
  const [restyling, setRestyling] = useState(false);
  const [stylePerformance, setStylePerformance] = useState<Record<string, { correct: number; total: number }>>({});
  const [recommendedStyle, setRecommendedStyle] = useState<LearningStyle | null>(null);
  const [answerRevealed, setAnswerRevealed] = useState(false);
  const [recordedScenes, setRecordedScenes] = useState<Record<string, boolean>>({});
  const [selectedRecallChoices, setSelectedRecallChoices] = useState<Record<string, number>>({});
  const [uploadingPdf, setUploadingPdf] = useState(false);
  const [slideshowError, setSlideshowError] = useState("");
  const [activeSlideshowScene, setActiveSlideshowScene] = useState(0);
  const [audioPlaying, setAudioPlaying] = useState(false);
  const slideshowAudio = useRef<Audio.Sound | null>(null);
  const restyleRequests = useRef(new Set<string>());
  const { width } = useWindowDimensions();
  const isWideWorkspace = width >= 1100;
  const companionStyle: LearningStyle =
    learningStyle === "infographic" ? "whiteboard" : "infographic";

  useEffect(() => () => {
    const sound = slideshowAudio.current;
    slideshowAudio.current = null;
    if (sound) void sound.unloadAsync().catch(() => undefined);
  }, []);

  const refreshStyleResults = async () => {
    const response = await fetch(
      `${API_BASE_URL}/v1/learning-style/results?user_id=${encodeURIComponent(userId)}`,
    );
    if (!response.ok) throw new Error("Learning-style results could not be loaded.");
    const payload = await response.json();
    setStylePerformance(payload.styles || {});
    setRecommendedStyle(payload.recommended_style || null);
  };

  useEffect(() => {
    void refreshStyleResults().catch((error: unknown) => {
      setSlideshowError(error instanceof Error ? error.message : "Learning profile is unavailable.");
    });
  }, [userId]);

  const imageUrlFor = (sceneIndex: number, style: LearningStyle) => {
    if (!slideshow) return "";
    if (style === slideshow.visual_style) {
      return `${API_BASE_URL}${slideshow.scenes[sceneIndex].image_url}`;
    }
    const imageUrl = styleImages[`${sceneIndex}:${style}`];
    return imageUrl ? `${API_BASE_URL}${imageUrl}` : "";
  };

  const ensureStyleImage = async (sceneIndex: number, style: LearningStyle) => {
    const key = `${sceneIndex}:${style}`;
    if (
      !slideshow ||
      style === slideshow.visual_style ||
      styleImages[key] ||
      restyleRequests.current.has(key)
    ) return;
    restyleRequests.current.add(key);
    setRestyling(true);
    setSlideshowError("");
    try {
      const response = await fetch(
        `${API_BASE_URL}/v1/educational/slideshows/${slideshow.job_id}/scenes/${sceneIndex + 1}/style`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ visual_style: style }),
        },
      );
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "This scene could not be restyled.");
      setStyleImages((images) => ({
        ...images,
        [`${sceneIndex}:${style}`]: payload.image_url,
      }));
    } catch (error) {
      setSlideshowError(error instanceof Error ? error.message : "Scene restyling failed.");
    } finally {
      restyleRequests.current.delete(key);
      setRestyling(false);
    }
  };

  useEffect(() => {
    if (!slideshow) return;
    void ensureStyleImage(activeSlideshowScene, learningStyle);
    if (dualScreen) void ensureStyleImage(activeSlideshowScene, companionStyle);
  }, [slideshow, activeSlideshowScene, learningStyle, dualScreen]);

  const submitSceneRecall = async (correct: boolean) => {
    const resultKey = `${activeSlideshowScene}:${learningStyle}`;
    if (!slideshow || recordedScenes[resultKey] !== undefined) return;
    setSlideshowError("");
    try {
      const response = await fetch(`${API_BASE_URL}/v1/learning-style/results`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: userId,
          visual_style: learningStyle,
          correct: correct ? 1 : 0,
          total: 1,
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "Your quiz result could not be saved.");
      setRecordedScenes((results) => ({ ...results, [resultKey]: correct }));
      setStylePerformance(payload.styles || {});
      setRecommendedStyle(payload.recommended_style || null);
    } catch (error) {
      setSlideshowError(error instanceof Error ? error.message : "Your quiz result could not be saved.");
    }
  };

  const submitMultipleChoiceRecall = () => {
    const key = `${activeSlideshowScene}:${learningStyle}`;
    const selected = selectedRecallChoices[key];
    const answer = slideshow?.scenes[activeSlideshowScene].recall_answer_index;
    if (selected === undefined || answer === undefined) return;
    void submitSceneRecall(selected === answer);
  };

  const selectLearningStyle = (style: LearningStyle) => {
    setAudioTextMode(false);
    setLearningStyle(style);
    void ensureStyleImage(activeSlideshowScene, style);
    if (dualScreen) {
      const companion: LearningStyle = style === "infographic" ? "whiteboard" : "infographic";
      void ensureStyleImage(activeSlideshowScene, companion);
    }
  };

  const installSlideshow = async (payload: unknown) => {
    if (!isStudentSlideshowPayload(payload)) {
      throw new Error("The server returned an invalid slideshow.");
    }
    const created: StudentSlideshow = {
      job_id: payload.job_id,
      title: payload.title,
      summary: payload.summary,
      visual_style: learningStyle,
      audio_url: payload.audio_url,
      scenes: payload.scenes,
    };
    const currentSound = slideshowAudio.current;
    slideshowAudio.current = null;
    if (currentSound) await currentSound.unloadAsync();
    setSlideshow(created);
    setStyleImages({});
    setActiveSlideshowScene(0);
    setAudioPlaying(false);
    setAudioTextMode(false);
    setAnswerRevealed(false);
    setRecordedScenes({});
    setSelectedRecallChoices({});
  };

  const toggleDualScreen = () => {
    const enabled = !dualScreen;
    setDualScreen(enabled);
    if (enabled) void ensureStyleImage(activeSlideshowScene, companionStyle);
  };

  const exportStudyNotes = async () => {
    if (!slideshow) return;
    const notes = [
      slideshow.title,
      slideshow.summary,
      "",
      "Key ideas",
      ...slideshow.scenes.map(
        (scene, index) => `${index + 1}. ${scene.heading}\n${scene.narration}`,
      ),
    ].join("\n\n");
    try {
      await Share.share({ title: `${slideshow.title} study notes`, message: notes });
    } catch (error) {
      setSlideshowError(error instanceof Error ? error.message : "Study notes could not be exported.");
    }
  };

  const uploadStudentPdf = async () => {
    setSlideshowError("");
    try {
      const selection = await DocumentPicker.getDocumentAsync({
        type: "application/pdf",
        copyToCacheDirectory: true,
      });
      if (selection.canceled) return;
      const selectedFile = selection.assets[0];
      const fileResponse = await fetch(selectedFile.uri);
      if (!fileResponse.ok) throw new Error("The selected PDF could not be opened.");
      const pdf = await fileResponse.blob();
      const form = new FormData();
      form.append("file", pdf, selectedFile.name);
      form.append("language", narrationLanguage);
      form.append("account_tier", accountTier === "free" ? "free" : "premium");
      form.append("visual_style", learningStyle);
      setUploadingPdf(true);
      const response = await fetch(`${API_BASE_URL}/v1/educational/slideshow`, {
        method: "POST",
        body: form,
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || "Your PDF could not be turned into a slideshow.");
      }
      await installSlideshow(payload);
    } catch (error) {
      setSlideshowError(error instanceof Error ? error.message : "PDF slideshow creation failed.");
    } finally {
      setUploadingPdf(false);
    }
  };

  const createTextSlideshow = async () => {
    if (!readerText.trim()) {
      setSlideshowError("Paste some study text before creating a visual lesson.");
      return;
    }
    setUploadingPdf(true);
    setSlideshowError("");
    try {
      const response = await fetch(`${API_BASE_URL}/v1/educational/slideshow/text`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: readerText.trim(),
          language: narrationLanguage,
          account_tier: accountTier === "free" ? "free" : "premium",
          visual_style: learningStyle,
        }),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || "Your text could not be turned into a slideshow.");
      }
      await installSlideshow(payload);
    } catch (error) {
      setSlideshowError(error instanceof Error ? error.message : "Text slideshow creation failed.");
    } finally {
      setUploadingPdf(false);
    }
  };

  const toggleSlideshowAudio = async () => {
    if (!slideshow) return;
    setSlideshowError("");
    try {
      let sound = slideshowAudio.current;
      if (!sound) {
        const assetUrl = slideshow.audio_url.startsWith("/")
          ? `${API_BASE_URL}${slideshow.audio_url}`
          : slideshow.audio_url;
        const playback = await Audio.Sound.createAsync(
          { uri: assetUrl },
          { shouldPlay: true },
          (status) => {
            if (!status.isLoaded) return;
            setAudioPlaying(status.isPlaying);
            if (status.durationMillis) {
              const progress = status.positionMillis / status.durationMillis;
              const totalWords = slideshow.scenes.reduce(
                (total, scene) => total + Math.max(1, scene.narration.trim().split(/\s+/).length),
                0,
              );
              let accumulatedWords = 0;
              const sceneIndex = slideshow.scenes.findIndex((scene) => {
                accumulatedWords += Math.max(1, scene.narration.trim().split(/\s+/).length);
                return progress <= accumulatedWords / totalWords;
              });
              if (sceneIndex >= 0) setActiveSlideshowScene(sceneIndex);
            }
            if (status.didJustFinish) setAudioPlaying(false);
          },
        );
        sound = playback.sound;
        slideshowAudio.current = sound;
        return;
      }
      const status = await sound.getStatusAsync();
      if (!status.isLoaded) throw new Error("Narration audio is not ready.");
      if (status.isPlaying) {
        await sound.pauseAsync();
        setAudioPlaying(false);
      } else if (status.didJustFinish) {
        await sound.replayAsync();
        setAudioPlaying(true);
      } else {
        await sound.playAsync();
        setAudioPlaying(true);
      }
    } catch (error) {
      setSlideshowError(error instanceof Error ? error.message : "Narration playback failed.");
    }
  };

  const advanceTour = () => {
    setTouring(true);
    setActiveScene((current) => {
      const next = (current + 1) % scenes.length;
      if (next === 0) setTouring(false);
      return next;
    });
  };

  const narrateReader = async () => {
    const text = readerText.trim() || scenes[activeScene].subtitle;
    setNarrating(true);
    setNarrationError("");
    try {
      const response = await fetch(`${API_BASE_URL}/v1/narrate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, language: "en" }),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail || "Narration could not be created.");
      }
      await Linking.openURL(
        `${API_BASE_URL}/v1/narrate?text=${encodeURIComponent(text)}&language=en`,
      );
    } catch (error) {
      setNarrationError(error instanceof Error ? error.message : "Narration is unavailable.");
    } finally {
      setNarrating(false);
    }
  };

  const generateWithGoogleAIStudio = async () => {
    setGenerating(true);
    setGenerationError("");
    try {
      const response = await fetch(`${API_BASE_URL}/v1/video/blueprint`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: readerText.trim() || scenes[activeScene].subtitle,
          language: "English",
          subject_and_cast: subjectAndCast,
          action_guidance: actionGuidance,
          camera_movement: cameraMovement,
          lighting_environment: lightingEnvironment,
          constraints_negative_prompt: constraints,
        }),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || "The video blueprint could not be created.");
      }
      if (!Array.isArray(payload.video_scenes) || payload.video_scenes.length !== 3) {
        throw new Error("The server returned an invalid three-scene video blueprint.");
      }
      setScenes(payload.video_scenes.map((scene: {
        title?: string;
        subtitle?: string;
        detail?: string;
        visual_prompt?: string;
      }, index: number) => ({
        title: scene.title || `Scene ${index + 1}`,
        subtitle: scene.subtitle || "",
        detail: scene.detail || "",
        visualPrompt: scene.visual_prompt || "",
      })));
      setActiveScene(0);
    } catch (error) {
      setGenerationError(error instanceof Error ? error.message : "Video generation is unavailable.");
    } finally {
      setGenerating(false);
    }
  };

  const recallScene = slideshow?.scenes[activeSlideshowScene];
  const currentResultKey = `${activeSlideshowScene}:${learningStyle}`;

  return (
    <ScrollView contentContainerStyle={[styles.content, isWideWorkspace && styles.desktopContent]}>
      <SectionTitle eyebrow="Study with visuals" title="Student Notes Slideshow" />
      <Text style={styles.pageIntro}>Choose the way you like to learn. Your lesson illustrations will match your visual style.</Text>
      <View style={[styles.workspaceColumns, isWideWorkspace && styles.workspaceColumnsWide]}>
        <View style={[styles.workspaceLeft, isWideWorkspace && styles.workspacePane]}>
      <View style={styles.videoCard}>
        <Text style={styles.lessonTitle}>Choose your learning lens</Text>
        <Text style={styles.lessonMeta}>Pick a style for this lesson. You can change it any time.</Text>
        <View style={styles.learningStyleList}>
          {learningStyles.map((style) => {
            const selected = learningStyle === style.key;
            return (
              <Pressable
                key={style.key}
                style={[styles.learningStyleCard, selected && styles.selectedLearningStyleCard]}
                onPress={() => setLearningStyle(style.key)}
                accessibilityRole="radio"
                accessibilityState={{ selected }}
                accessibilityLabel={`${style.title}. Best for ${style.bestFor}. ${style.description}`}
              >
                <Text style={styles.learningStyleIcon}>{style.icon}</Text>
                <View style={styles.learningStyleCopy}>
                  <Text style={styles.learningStyleTitle}>{style.title}</Text>
                  <Text style={styles.learningStyleBestFor}>{style.bestFor}</Text>
                  <Text style={styles.lessonMeta}>{style.description}</Text>
                </View>
                <Text style={selected ? styles.learningStyleSelected : styles.learningStyleUnselected}>
                  {selected ? "✓" : "○"}
                </Text>
              </Pressable>
            );
          })}
        </View>
      </View>
      <View style={styles.videoCard}>
        <Text style={styles.lessonTitle}>Start with your notes</Text>
        <Text style={styles.lessonMeta}>Paste a chapter or lecture excerpt, or choose a PDF. LETSRD turns it into a narrated, illustrated lesson.</Text>
        <TextInput
          style={styles.aiInput}
          multiline
          maxLength={50_000}
          value={readerText}
          onChangeText={onReaderTextChange}
          placeholder="Paste textbook text or class notes…"
          placeholderTextColor={colors.muted}
        />
        <Pressable
          style={styles.outlineButton}
          onPress={() => void createTextSlideshow()}
          disabled={uploadingPdf || !readerText.trim()}
        >
          <Text style={styles.outlineButtonText}>
            {uploadingPdf ? "Creating your text lesson…" : "Create lesson from pasted text"}
          </Text>
        </Pressable>
        <Text style={styles.lessonMeta}>Or upload a PDF:</Text>
        <Text style={styles.promptLabel}>Narration and subtitle language</Text>
        <View style={styles.formatRow}>
          {narrationLanguages.map((language) => (
            <Pressable
              key={language.code}
              onPress={() => setNarrationLanguage(language.code)}
              style={[styles.formatButton, narrationLanguage === language.code && styles.selectedFormat]}
              accessibilityRole="radio"
              accessibilityState={{ selected: narrationLanguage === language.code }}
            >
              <Text style={[styles.formatText, narrationLanguage === language.code && styles.selectedFormatText]}>
                {language.label}
              </Text>
            </Pressable>
          ))}
        </View>
        {recommendedStyle ? (
          <Text style={styles.recommendationNote}>
            Quiz results suggest {learningStyles.find((style) => style.key === recommendedStyle)?.title}.
          </Text>
        ) : null}
        <Pressable
          style={styles.primaryButtonWide}
          onPress={uploadStudentPdf}
          disabled={uploadingPdf}
        >
          <Text style={styles.primaryButtonText}>
            {uploadingPdf ? "Creating your illustrated lesson..." : "Choose a student-notes PDF"}
          </Text>
        </Pressable>
        {uploadingPdf ? <ActivityIndicator color={colors.teal} style={styles.loadingIndicator} /> : null}
        {slideshowError ? <Text style={styles.errorText}>{slideshowError}</Text> : null}
      </View>
        </View>
        <View style={[styles.workspaceCenter, isWideWorkspace && styles.workspaceCenterPane]}>
      {slideshow ? (
        <View style={styles.videoCard}>
          <Text style={styles.lessonTitle}>{slideshow.title}</Text>
          <Text style={styles.lessonMeta}>{slideshow.summary}</Text>
          <Text style={styles.videoSceneLabel}>
            SCENE {activeSlideshowScene + 1} OF {slideshow.scenes.length}
          </Text>
          {audioTextMode ? (
            <View style={styles.audioTextStage}>
              <Text style={styles.videoSceneLabel}>AUDIO-TEXT MODE</Text>
              <Text style={styles.audioTextNarration}>{slideshow.scenes[activeSlideshowScene].narration}</Text>
            </View>
          ) : (
            <View style={[styles.playerImageRow, dualScreen && styles.dualPlayerImageRow]}>
              <Pressable style={styles.playerImagePane} onPress={() => setZoomVisible(true)}>
                {imageUrlFor(activeSlideshowScene, learningStyle) ? (
                  <Image
                    style={styles.slideImage}
                    source={{ uri: imageUrlFor(activeSlideshowScene, learningStyle) }}
                    accessibilityLabel={slideshow.scenes[activeSlideshowScene].visual_prompt}
                  />
                ) : (
                  <View style={[styles.slideImage, styles.secondaryLoadingPane]}>
                    <ActivityIndicator color={colors.teal} />
                    <Text style={styles.lessonMeta}>Preparing this learning lens…</Text>
                  </View>
                )}
                {showSubtitles ? (
                  <View style={styles.floatingSubtitle}>
                    <Text style={styles.videoSubtitle}>{slideshow.scenes[activeSlideshowScene].narration}</Text>
                  </View>
                ) : null}
              </Pressable>
              {dualScreen ? (
                <View style={styles.playerImagePane}>
                  {imageUrlFor(activeSlideshowScene, companionStyle) ? (
                    <Pressable onPress={() => setZoomVisible(true)}>
                      <Image
                        style={styles.slideImage}
                        source={{ uri: imageUrlFor(activeSlideshowScene, companionStyle) }}
                        accessibilityLabel={`${companionStyle}: ${slideshow.scenes[activeSlideshowScene].visual_prompt}`}
                      />
                    </Pressable>
                  ) : (
                    <View style={[styles.slideImage, styles.secondaryLoadingPane]}>
                      <ActivityIndicator color={colors.teal} />
                      <Text style={styles.lessonMeta}>Creating second view…</Text>
                    </View>
                  )}
                </View>
              ) : null}
            </View>
          )}
          {restyling ? <ActivityIndicator color={colors.teal} style={styles.loadingIndicator} /> : null}
          <Text style={styles.slideHeading}>{slideshow.scenes[activeSlideshowScene].heading}</Text>
          <View style={styles.slideControls}>
            <Pressable
              style={[styles.outlineButton, styles.slideControlButton]}
              onPress={() => {
                const next = Math.max(0, activeSlideshowScene - 1);
                setActiveSlideshowScene(next);
                setAnswerRevealed(false);
                void ensureStyleImage(next, learningStyle);
                if (dualScreen) void ensureStyleImage(next, companionStyle);
              }}
            >
              <Text style={styles.outlineButtonText}>Previous scene</Text>
            </Pressable>
            <Pressable
              style={[styles.outlineButton, styles.slideControlButton]}
              onPress={() => {
                const next = Math.min(slideshow.scenes.length - 1, activeSlideshowScene + 1);
                setActiveSlideshowScene(next);
                setAnswerRevealed(false);
                void ensureStyleImage(next, learningStyle);
                if (dualScreen) void ensureStyleImage(next, companionStyle);
              }}
            >
              <Text style={styles.outlineButtonText}>Next scene</Text>
            </Pressable>
          </View>
          <Pressable style={styles.primaryButtonWide} onPress={toggleSlideshowAudio}>
            <Text style={styles.primaryButtonText}>
              {audioPlaying ? "Pause narration" : "Play narrated slideshow"}
            </Text>
          </Pressable>
          <View style={styles.playerToolbar}>
            <Pressable style={styles.playerToolButton} onPress={() => setZoomVisible(true)}>
              <Text style={styles.outlineButtonText}>⌕ Zoom</Text>
            </Pressable>
            <Pressable style={styles.playerToolButton} onPress={() => setShowSubtitles((visible) => !visible)}>
              <Text style={styles.outlineButtonText}>{showSubtitles ? "Hide subtitles" : "Show subtitles"}</Text>
            </Pressable>
            <Pressable style={styles.playerToolButton} onPress={toggleDualScreen}>
              <Text style={styles.outlineButtonText}>{dualScreen ? "Single view" : "Dual view"}</Text>
            </Pressable>
          </View>
          <Text style={styles.dockHeading}>Learning lens</Text>
          <View style={styles.styleDock}>
            {learningStyles.map((style) => (
              <Pressable
                key={style.key}
                style={[styles.dockStyleButton, learningStyle === style.key && !audioTextMode && styles.selectedDockStyleButton]}
                onPress={() => selectLearningStyle(style.key)}
                disabled={restyling}
                accessibilityRole="radio"
                accessibilityState={{ selected: learningStyle === style.key && !audioTextMode }}
              >
                <Text style={styles.dockStyleLabel}>{style.icon} {style.title}</Text>
              </Pressable>
            ))}
            <Pressable
              style={[styles.dockStyleButton, audioTextMode && styles.selectedDockStyleButton]}
              onPress={() => setAudioTextMode(true)}
              accessibilityRole="radio"
              accessibilityState={{ selected: audioTextMode }}
            >
              <Text style={styles.dockStyleLabel}>🔊 Audio-text</Text>
            </Pressable>
          </View>
          {recommendedStyle ? (
            <Text style={styles.recommendationNote}>
              Recommended from your quiz results: {learningStyles.find((style) => style.key === recommendedStyle)?.title}
            </Text>
          ) : null}
          <View style={styles.practiceCard}>
            <Text style={styles.practiceTag}>QUICK RECALL · SCENE {activeSlideshowScene + 1}</Text>
            {recallScene?.recall_question &&
            recallScene.recall_choices?.length === 3 &&
            typeof recallScene.recall_answer_index === "number" ? (
              <>
                <Text style={styles.practiceQuestion}>{recallScene.recall_question}</Text>
                {recallScene.recall_choices.map((choice, choiceIndex) => (
                  <Pressable
                    key={`${choiceIndex}-${choice}`}
                    style={[
                      styles.recallChoice,
                      selectedRecallChoices[currentResultKey] === choiceIndex && styles.selectedRecallChoice,
                      recordedScenes[currentResultKey] !== undefined &&
                        choiceIndex === recallScene.recall_answer_index && styles.correctAnswer,
                    ]}
                    disabled={recordedScenes[currentResultKey] !== undefined}
                    onPress={() => setSelectedRecallChoices((answers) => ({
                      ...answers,
                      [currentResultKey]: choiceIndex,
                    }))}
                    accessibilityRole="radio"
                    accessibilityState={{ selected: selectedRecallChoices[currentResultKey] === choiceIndex }}
                  >
                    <Text style={styles.answerText}>{choice}</Text>
                  </Pressable>
                ))}
                {recordedScenes[currentResultKey] === undefined ? (
                  <Pressable
                    style={styles.primaryButtonWide}
                    onPress={submitMultipleChoiceRecall}
                    disabled={selectedRecallChoices[currentResultKey] === undefined}
                  >
                    <Text style={styles.primaryButtonText}>Check answer</Text>
                  </Pressable>
                ) : (
                  <Text style={recordedScenes[currentResultKey] ? styles.successText : styles.retryText}>
                    {recordedScenes[currentResultKey] ? "Correct — recalled and recorded." : "Not quite. Review the scene and try this lens again."}
                  </Text>
                )}
              </>
            ) : (
              <>
                <Text style={styles.practiceQuestion}>
                  What is the key idea in “{slideshow.scenes[activeSlideshowScene].heading}”?
                </Text>
                <Pressable style={styles.outlineButton} onPress={() => setAnswerRevealed((visible) => !visible)}>
                  <Text style={styles.outlineButtonText}>{answerRevealed ? "Hide answer" : "Reveal answer"}</Text>
                </Pressable>
                {answerRevealed ? (
                  <>
                    <Text style={styles.lessonMeta}>{slideshow.scenes[activeSlideshowScene].narration}</Text>
                    {recordedScenes[currentResultKey] === undefined ? (
                      <View style={styles.slideControls}>
                        <Pressable style={[styles.outlineButton, styles.slideControlButton]} onPress={() => void submitSceneRecall(true)}>
                          <Text style={styles.outlineButtonText}>I recalled it</Text>
                        </Pressable>
                        <Pressable style={[styles.outlineButton, styles.slideControlButton]} onPress={() => void submitSceneRecall(false)}>
                          <Text style={styles.outlineButtonText}>I need another look</Text>
                        </Pressable>
                      </View>
                    ) : (
                      <Text style={styles.successText}>
                        {recordedScenes[currentResultKey] ? "Recall recorded." : "Review recorded. Keep practicing."}
                      </Text>
                    )}
                  </>
                ) : null}
              </>
            )}
            {Object.entries(stylePerformance).map(([style, result]) => (
              <Text key={style} style={styles.lessonMeta}>
                {learningStyles.find((option) => option.key === style)?.title}: {result.correct}/{result.total} recalled
              </Text>
            ))}
          </View>
        </View>
      ) : null}
        </View>
        {slideshow ? (
          <View style={[styles.workspaceRight, isWideWorkspace && styles.workspacePane]}>
            <View style={styles.studyHubCard}>
              <Text style={styles.practiceTag}>STUDY HUB</Text>
              <Text style={styles.lessonTitle}>Key ideas from this lesson</Text>
              {slideshow.scenes.map((scene, index) => (
                <View style={styles.glossaryRow} key={`${index}-${scene.heading}`}>
                  <Text style={styles.learningStyleTitle}>{scene.heading}</Text>
                  <Text style={styles.lessonMeta}>{scene.narration}</Text>
                </View>
              ))}
              <Pressable style={styles.outlineButton} onPress={() => void exportStudyNotes()}>
                <Text style={styles.outlineButtonText}>Export summary & notes</Text>
              </Pressable>
            </View>
          </View>
        ) : null}
      </View>
      <SectionTitle eyebrow="Creative tools" title="AI Video Workspace" />
      <Text style={styles.pageIntro}>Create a consistent scene-by-scene video prompt from your reader context.</Text>
      <View style={styles.videoCard}>
        <Text style={styles.lessonTitle}>Video prompt settings</Text>
        <Text style={styles.lessonMeta}>Keep the cast, movement, camera, lighting, and rendering constraints consistent.</Text>
        <PromptField label="Subject & cast" value={subjectAndCast} onChangeText={setSubjectAndCast} />
        <PromptField label="Action guidance" value={actionGuidance} onChangeText={setActionGuidance} />
        <PromptField label="Camera movement" value={cameraMovement} onChangeText={setCameraMovement} />
        <PromptField label="Lighting & environment" value={lightingEnvironment} onChangeText={setLightingEnvironment} />
        <PromptField label="Constraints / negative prompt" value={constraints} onChangeText={setConstraints} />
      </View>
      <View style={styles.videoCard}>
        <View style={styles.videoSurface}>
          <Text style={styles.videoSceneLabel}>SCENE {activeScene + 1}</Text>
          <Text style={styles.videoPlay}>▶</Text>
          <Text style={styles.videoSubtitle}>{scenes[activeScene].subtitle}</Text>
        </View>
        <Pressable style={styles.primaryButtonWide} onPress={advanceTour}>
          <Text style={styles.primaryButtonText}>{touring ? "Next scene" : "Start Guided Tour"}</Text>
        </Pressable>
        <Pressable style={styles.outlineButton} onPress={narrateReader} disabled={narrating}>
          <Text style={styles.outlineButtonText}>{narrating ? "Preparing narration..." : "🔊 Narrate reader context"}</Text>
        </Pressable>
        <Pressable style={styles.outlineButton} onPress={generateWithGoogleAIStudio} disabled={generating}>
          <Text style={styles.outlineButtonText}>{generating ? "Creating AI scenes..." : "✨ Generate three video prompts"}</Text>
        </Pressable>
        {narrationError ? <Text style={styles.errorText}>{narrationError}</Text> : null}
        {generationError ? <Text style={styles.errorText}>{generationError}</Text> : null}
      </View>
      {scenes.map((scene, index) => (
        <Pressable
          key={scene.title}
          onPress={() => {
            setActiveScene(index);
            setTouring(false);
          }}
          style={[styles.sceneCard, activeScene === index && styles.activeSceneCard]}
        >
          <Text style={styles.sceneNumber}>{index + 1}</Text>
          <View style={styles.lessonDetails}>
            <Text style={styles.lessonTitle}>{scene.title}</Text>
            <Text style={styles.lessonMeta}>{scene.detail}</Text>
            {scene.visualPrompt ? <Text style={styles.promptPreview}>{scene.visualPrompt}</Text> : null}
          </View>
          <Text style={styles.chevron}>›</Text>
        </Pressable>
      ))}
      <Modal visible={zoomVisible && Boolean(slideshow)} transparent animationType="fade" onRequestClose={() => setZoomVisible(false)}>
        <Pressable style={styles.zoomBackdrop} onPress={() => setZoomVisible(false)}>
          {slideshow && !audioTextMode ? (
            <Image
              style={styles.zoomImage}
              resizeMode="contain"
              source={{ uri: imageUrlFor(activeSlideshowScene, learningStyle) }}
              accessibilityLabel={slideshow.scenes[activeSlideshowScene].visual_prompt}
            />
          ) : (
            <Text style={styles.zoomText}>{slideshow?.scenes[activeSlideshowScene].narration}</Text>
          )}
          <Text style={styles.zoomClose}>Tap to close</Text>
        </Pressable>
      </Modal>
    </ScrollView>
  );
}

function PaymentsScreen({
  sandboxMode,
  accountTier,
  onUpgrade,
}: {
  sandboxMode: boolean;
  accountTier: "free" | "premium_trial" | "premium_paid";
  onUpgrade: () => void;
}) {
  const [method, setMethod] = useState<"mpesa" | "airtel" | "card">("mpesa");
  const [phone, setPhone] = useState("");
  const [notice, setNotice] = useState("");
  const [processing, setProcessing] = useState(false);
  const [successVisible, setSuccessVisible] = useState(false);
  const paymentTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const labels = {
    mpesa: "M-Pesa Express 🇰🇪",
    airtel: "Airtel Money 🌍",
    card: "International Card 💳",
  };

  useEffect(() => () => {
    if (paymentTimer.current) {
      clearTimeout(paymentTimer.current);
    }
  }, []);

  const executePayment = () => {
    if (method !== "mpesa") {
      setNotice("Payment sandbox ready. No charge has been submitted.");
      return;
    }
    if (!phone.trim()) {
      setNotice("Enter a Safaricom phone number to send the STK prompt.");
      return;
    }

    setNotice("");
    setProcessing(true);
    paymentTimer.current = setTimeout(() => {
      setProcessing(false);
      setSuccessVisible(true);
      onUpgrade();
    }, 5000);
  };

  return (
    <>
      <ScrollView contentContainerStyle={styles.content}>
      <SectionTitle eyebrow="Account" title="Payment hub" />
      <Text style={styles.pageIntro}>Choose a payment method for your premium learning workspace.</Text>
      {sandboxMode ? (
        <View style={styles.sandboxBadge}>
          <Text style={styles.sandboxBadgeText}>🔧 Developer Sandbox billing preview</Text>
        </View>
      ) : null}
      <Text style={styles.accountStatus}>Account status: {accountTier}</Text>
      <View style={styles.paymentTiles}>
        {(Object.keys(labels) as Array<"mpesa" | "airtel" | "card">).map((key) => (
          <Pressable key={key} onPress={() => setMethod(key)} style={[styles.paymentTile, method === key && styles.selectedPaymentTile]}>
            <Text style={styles.paymentTileText}>{labels[key]}</Text>
          </Pressable>
        ))}
      </View>
      {method !== "card" ? (
        <TextInput
          style={styles.loginInput}
          value={phone}
          onChangeText={setPhone}
          placeholder="+254 700 000 000"
          placeholderTextColor={colors.muted}
          keyboardType="phone-pad"
        />
      ) : null}
      <Pressable style={styles.primaryButtonWide} onPress={executePayment} disabled={processing}>
        <Text style={styles.primaryButtonText}>{method === "mpesa" ? "Trigger M-Pesa STK Push 🚀" : method === "airtel" ? "Process Airtel Wallet Authorization" : "Open secure card checkout"}</Text>
      </Pressable>
      {notice ? <Text style={styles.successText}>{notice}</Text> : null}
      </ScrollView>
      <Modal visible={processing} transparent animationType="fade">
        <View style={styles.modalBackdrop}>
          <View style={styles.processingCard}>
            <ActivityIndicator size="large" color={colors.teal} />
            <Text style={styles.modalTitle}>Sending STK Prompt to handset... 🚀</Text>
            <Text style={styles.modalBody}>Waiting for the simulated Daraja response.</Text>
          </View>
        </View>
      </Modal>
      <Modal visible={successVisible} transparent animationType="fade" onRequestClose={() => setSuccessVisible(false)}>
        <View style={styles.modalBackdrop}>
          <View style={styles.successModalCard}>
            <Text style={styles.successEmoji}>🎉</Text>
            <Text style={styles.modalTitle}>Premium Status Unlocked!</Text>
            <Text style={styles.modalBody}>M-Pesa Transaction Verified.</Text>
            <Pressable style={styles.primaryButtonWide} onPress={() => setSuccessVisible(false)}>
              <Text style={styles.primaryButtonText}>Continue learning</Text>
            </Pressable>
          </View>
        </View>
      </Modal>
    </>
  );
}

function LibraryScreen() {
  const [notice, setNotice] = useState("");
  return (
    <ScrollView contentContainerStyle={styles.content}>
      <SectionTitle eyebrow="Your materials" title="Study library" />
      <Text style={styles.pageIntro}>Your PDFs, audio lessons and ebooks in one calm place.</Text>
      <Pressable style={styles.uploadCard} onPress={() => setNotice("PDF import is ready in the browser workspace. Open LETSRD on your computer to select a file.")}>
        <Text style={styles.uploadIcon}>＋</Text>
        <View>
          <Text style={styles.lessonTitle}>Add a study PDF</Text>
          <Text style={styles.lessonMeta}>Read it, listen to it, keep it offline</Text>
        </View>
      </Pressable>
      {notice ? <Text style={styles.successText}>{notice}</Text> : null}
      {["Computer Organisation", "Topic 3 Calculus", "Python Cheatsheet"].map((title, index) => (
        <View style={styles.libraryRow} key={title}>
          <View style={[styles.lessonIcon, index === 1 && { backgroundColor: colors.lavender }]}>
            <Text>PDF</Text>
          </View>
          <View style={styles.lessonDetails}>
            <Text style={styles.lessonTitle}>{title}</Text>
            <Text style={styles.lessonMeta}>{index === 0 ? "Audio ready offline" : "Not started"}</Text>
          </View>
          <Text style={index === 0 ? styles.downloaded : styles.chevron}>{index === 0 ? "✓" : "›"}</Text>
        </View>
      ))}
    </ScrollView>
  );
}

function FocusScreen() {
  const [answer, setAnswer] = useState<"idle" | "correct" | "tryAgain">("idle");
  return (
    <ScrollView contentContainerStyle={styles.content}>
      <SectionTitle eyebrow="Daily reset" title="Focus before you listen" />
      <Text style={styles.pageIntro}>One small puzzle. One clear mind. Take your time.</Text>
      <View style={styles.focusCard}>
        <View style={styles.focusTop}><Text style={styles.focusLabel}>TODAY'S PUZZLE</Text><Text style={styles.focusCount}>1 of 1</Text></View>
        <Text style={styles.puzzlePrompt}>What number comes next?</Text>
        <Text style={styles.sequence}>2  ·  4  ·  8  ·  16  ·  ?</Text>
        <View style={styles.answerRow}>
          {["24", "32", "36"].map((option) => (
            <Pressable
              key={option}
              style={[styles.answerButton, answer === "correct" && option === "32" && styles.correctAnswer]}
              onPress={() => setAnswer(option === "32" ? "correct" : "tryAgain")}
            >
              <Text style={styles.answerText}>{option}</Text>
            </Pressable>
          ))}
        </View>
        {answer !== "idle" && <Text style={answer === "correct" ? styles.successText : styles.retryText}>
          {answer === "correct" ? "Nice work. Your mind is warmed up." : "Almost there. Look for the pattern again."}
        </Text>}
      </View>
      <View style={styles.tipCard}>
        <Text style={styles.tipIcon}>♡</Text>
        <View style={styles.tipCopy}>
          <Text style={styles.tipTitle}>A gentle reminder</Text>
          <Text style={styles.lessonMeta}>There is no timer here. Focus is about noticing, not rushing.</Text>
        </View>
      </View>
    </ScrollView>
  );
}

function QuestionsScreen() {
  const [hintVisible, setHintVisible] = useState(false);
  const [answering, setAnswering] = useState(false);
  return (
    <ScrollView contentContainerStyle={styles.content}>
      <SectionTitle eyebrow="Active recall" title="Practice what matters" />
      <Text style={styles.pageIntro}>Small questions turn mistakes into stronger understanding.</Text>
      <View style={styles.practiceCard}>
        <View style={styles.practiceHeader}><Text style={styles.practiceTag}>FROM FAILED TEST</Text><Text style={styles.practiceDots}>•••</Text></View>
        <Text style={styles.practiceQuestion}>Explain binary addition in your own words, then give one real example.</Text>
        <Pressable style={styles.outlineButton} onPress={() => setHintVisible((visible) => !visible)}>
          <Text style={styles.outlineButtonText}>{hintVisible ? "Hide hint" : "Reveal a helpful hint"}</Text>
        </Pressable>
        {hintVisible ? <Text style={styles.lessonMeta}>Hint: split the binary addition into place values and carry from right to left.</Text> : null}
      </View>
      <View style={styles.practiceCard}>
        <View style={styles.practiceHeader}><Text style={styles.practiceTag}>CREATIVE THINKING</Text><Text style={styles.practiceDots}>•••</Text></View>
        <Text style={styles.practiceQuestion}>If memory had a waiting room, what would happen when it became full?</Text>
        <Pressable style={styles.outlineButton} onPress={() => setAnswering(true)}>
          <Text style={styles.outlineButtonText}>{answering ? "Answer box ready below" : "Start answering"}</Text>
        </Pressable>
        {answering ? (
          <TextInput
            style={styles.loginInput}
            placeholder="Write your answer..."
            placeholderTextColor={colors.muted}
            multiline
          />
        ) : null}
      </View>
    </ScrollView>
  );
}

function SettingsScreen({
  userId,
  initialEmail,
}: {
  userId: string;
  initialEmail: string;
}) {
  const [givenName, setGivenName] = useState("Alex");
  const [email, setEmail] = useState(initialEmail);
  const [subject, setSubject] = useState("General learning");
  const [notice, setNotice] = useState("");
  const [saving, setSaving] = useState(false);

  const saveProfile = async () => {
    setSaving(true);
    setNotice("");
    try {
      const response = await fetch(`${API_BASE_URL}/v1/profile`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: userId, given_name: givenName, email, subject }),
      });
      if (!response.ok) throw new Error("Profile could not be saved.");
      setNotice("Profile saved securely on the LETSRD backend.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Profile sync is unavailable.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <ScrollView contentContainerStyle={styles.content}>
      <SectionTitle eyebrow="Account" title="Profile & settings" />
      <Text style={styles.pageIntro}>Keep your learning identity and preferences synchronized with LETSRD.</Text>
      <TextInput style={styles.loginInput} value={givenName} onChangeText={setGivenName} placeholder="Name" placeholderTextColor={colors.muted} />
      <TextInput style={styles.loginInput} value={email} onChangeText={setEmail} placeholder="Email" placeholderTextColor={colors.muted} keyboardType="email-address" autoCapitalize="none" />
      <TextInput style={styles.loginInput} value={subject} onChangeText={setSubject} placeholder="Learning focus" placeholderTextColor={colors.muted} />
      <View style={styles.securityCard}>
        <Text style={styles.lessonTitle}>Security boundary</Text>
        <Text style={styles.lessonMeta}>Provider keys stay on the backend. This profile sync does not store your password in the mobile app.</Text>
      </View>
      <Pressable style={styles.primaryButtonWide} onPress={saveProfile} disabled={saving}>
        <Text style={styles.primaryButtonText}>{saving ? "Saving profile..." : "Save profile online"}</Text>
      </Pressable>
      {notice ? <Text style={styles.successText}>{notice}</Text> : null}
    </ScrollView>
  );
}

function AIStudioScreen({ onReaderTextChange }: { onReaderTextChange: (text: string) => void }) {
  const [text, setText] = useState("");
  const [targetLanguage, setTargetLanguage] = useState("English");
  const [format, setFormat] = useState<"translation" | "notes" | "letter" | "report">("translation");
  const [result, setResult] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const transform = async () => {
    if (!text.trim()) {
      setError("Enter text, a message, or a lecture excerpt first.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${API_BASE_URL}/v1/transform`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text,
          target_language: targetLanguage,
          output_format: format,
          user_id: "mobile-demo-user",
        }),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || "The AI service could not process this request.");
      }
      setResult(payload.result);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "The AI service is unavailable.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <ScrollView contentContainerStyle={styles.content}>
      <SectionTitle eyebrow="Language AI" title="Translate or make sense of anything" />
      <Text style={styles.pageIntro}>
        Turn text into a translation, clear notes, a letter, or a report.
      </Text>
      <TextInput
        style={styles.aiInput}
        multiline
        value={text}
        onChangeText={(value) => {
          setText(value);
          onReaderTextChange(value);
        }}
        placeholder="Paste text or a lecture excerpt..."
        placeholderTextColor={colors.muted}
      />
      <TextInput
        style={styles.languageInput}
        value={targetLanguage}
        onChangeText={setTargetLanguage}
        placeholder="Target language"
        placeholderTextColor={colors.muted}
      />
      <View style={styles.formatRow}>
        {(["translation", "notes", "letter", "report"] as const).map((option) => (
          <Pressable
            key={option}
            style={[styles.formatButton, format === option && styles.selectedFormat]}
            onPress={() => setFormat(option)}
          >
            <Text style={[styles.formatText, format === option && styles.selectedFormatText]}>
              {option}
            </Text>
          </Pressable>
        ))}
      </View>
      <Pressable style={styles.primaryButton} onPress={transform} disabled={loading}>
        <Text style={styles.primaryButtonText}>{loading ? "Working..." : "Transform text"}</Text>
      </Pressable>
      {error ? <Text style={styles.errorText}>{error}</Text> : null}
      {result ? (
        <View style={styles.resultCard}>
          <Text style={styles.resultLabel}>RESULT</Text>
          <Text style={styles.resultText}>{result}</Text>
        </View>
      ) : null}
    </ScrollView>
  );
}

export default function App() {
  const [authenticated, setAuthenticated] = useState(false);
  const [sandboxMode, setSandboxMode] = useState(false);
  const [accountTier, setAccountTier] = useState<"free" | "premium_trial" | "premium_paid">("free");
  const [userEmail, setUserEmail] = useState("");
  const [tab, setTab] = useState<Tab>("Home");
  const [readerText, setReaderText] = useState("");
  if (!authenticated) {
    return (
      <SafeAreaView style={styles.safeArea}>
        <StatusBar style="dark" />
        <LoginScreen
          onUnlock={(isSandbox, email) => {
            setSandboxMode(isSandbox);
            setUserEmail(email);
            setAuthenticated(true);
          }}
        />
      </SafeAreaView>
    );
  }
  const screen = tab === "Home" ? <HomeScreen onNavigate={setTab} /> :
    tab === "Library" ? <LibraryScreen /> :
    tab === "Focus" ? <FocusScreen /> : <QuestionsScreen />;
  const activeScreen = tab === "AI Studio" ? <AIStudioScreen onReaderTextChange={setReaderText} /> :
    tab === "AI Video" ? (
      <VideoWorkspaceScreen
        readerText={readerText}
        onReaderTextChange={setReaderText}
        accountTier={accountTier}
        userId={userEmail || "mobile-user"}
      />
    ) :
    tab === "Payments" ? (
      <PaymentsScreen
        sandboxMode={sandboxMode}
        accountTier={accountTier}
        onUpgrade={() => setAccountTier("premium_paid")}
      />
    ) : tab === "Settings" ? (
      <SettingsScreen userId={userEmail || "mobile-user"} initialEmail={userEmail} />
    ) : screen;

  return (
    <SafeAreaView style={styles.safeArea}>
      <StatusBar style="dark" />
      {activeScreen}
      <View style={styles.tabBar}>
        {tabs.map((item) => (
          <Pressable style={styles.tabItem} key={item.key} onPress={() => setTab(item.key)}>
            <Text style={[styles.tabIcon, tab === item.key && styles.activeTab]}>{item.icon}</Text>
            <Text style={[styles.tabLabel, tab === item.key && styles.activeTab]}>{item.label}</Text>
          </Pressable>
        ))}
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: colors.cream },
  content: { padding: spacing.lg, paddingBottom: 120 },
  desktopContent: { width: "100%", maxWidth: 1800, alignSelf: "center" },
  workspaceColumns: { gap: spacing.md },
  workspaceColumnsWide: { flexDirection: "row", alignItems: "flex-start" },
  workspaceLeft: { width: "100%" },
  workspaceCenter: { width: "100%" },
  workspaceRight: { width: "100%" },
  workspacePane: { flex: 1, width: undefined },
  workspaceCenterPane: { flex: 2, width: undefined },
  loginContent: { flexGrow: 1, justifyContent: "center", padding: spacing.lg },
  loginMark: { color: colors.tealDark, fontSize: 14, fontWeight: "900", letterSpacing: 2 },
  loginTitle: { color: colors.ink, fontSize: 32, lineHeight: 38, fontWeight: "900", marginTop: spacing.md },
  loginCard: { backgroundColor: colors.surface, borderRadius: 22, padding: spacing.lg, borderWidth: 1, borderColor: colors.border, marginTop: spacing.lg },
  loginInput: { backgroundColor: colors.cream, borderRadius: 12, borderWidth: 1, borderColor: colors.border, color: colors.ink, padding: spacing.md, marginBottom: spacing.sm },
  primaryButtonWide: { alignItems: "center", backgroundColor: colors.teal, borderRadius: 12, paddingVertical: 13, marginTop: spacing.sm },
  googleButton: { alignItems: "center", borderWidth: 1, borderColor: colors.teal, borderRadius: 12, paddingVertical: 12, marginTop: spacing.sm },
  googleButtonText: { color: colors.tealDark, fontSize: 13, fontWeight: "800" },
  sandboxLink: { color: colors.coral, textAlign: "center", fontSize: 13, fontWeight: "800", marginTop: spacing.lg },
  motivationCard: { backgroundColor: "#FFF3DD", borderRadius: 18, padding: spacing.md, marginTop: spacing.lg },
  motivationText: { color: colors.ink, fontSize: 15, fontWeight: "800", lineHeight: 22 },
  videoCard: { backgroundColor: colors.surface, borderRadius: 20, padding: spacing.md, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.lg },
  learningStyleList: { gap: spacing.sm, marginTop: spacing.md },
  learningStyleCard: { backgroundColor: colors.cream, borderRadius: 14, borderWidth: 1, borderColor: colors.border, padding: spacing.md, flexDirection: "row", alignItems: "center" },
  selectedLearningStyleCard: { backgroundColor: colors.mist, borderColor: colors.teal, borderWidth: 1.5 },
  learningStyleIcon: { fontSize: 24, marginRight: spacing.sm },
  learningStyleCopy: { flex: 1 },
  learningStyleTitle: { color: colors.ink, fontSize: 14, fontWeight: "800" },
  learningStyleBestFor: { color: colors.tealDark, fontSize: 11, fontWeight: "700", marginTop: 4 },
  learningStyleSelected: { color: colors.tealDark, fontSize: 20, fontWeight: "900", marginLeft: spacing.sm },
  learningStyleUnselected: { color: colors.muted, fontSize: 20, marginLeft: spacing.sm },
  promptField: { marginTop: spacing.md },
  promptLabel: { color: colors.ink, fontSize: 13, fontWeight: "800", marginBottom: spacing.xs },
  promptInput: { backgroundColor: colors.cream, borderRadius: 12, borderWidth: 1, borderColor: colors.border, color: colors.ink, padding: spacing.md, minHeight: 64, textAlignVertical: "top" },
  promptPreview: { color: colors.inkSoft, fontSize: 12, lineHeight: 18, marginTop: spacing.sm },
  videoSurface: { backgroundColor: colors.ink, borderRadius: 16, minHeight: 245, padding: spacing.md, justifyContent: "center", alignItems: "center", marginBottom: spacing.md },
  slideImage: { width: "100%", height: 230, borderRadius: 14, backgroundColor: colors.cream, marginTop: spacing.sm },
  playerImageRow: { flexDirection: "row", gap: spacing.sm },
  dualPlayerImageRow: { alignItems: "flex-start" },
  playerImagePane: { flex: 1, position: "relative" },
  secondaryLoadingPane: { alignItems: "center", justifyContent: "center", padding: spacing.md },
  floatingSubtitle: { position: "absolute", left: spacing.sm, right: spacing.sm, bottom: spacing.sm, backgroundColor: "rgba(18, 48, 74, 0.86)", borderRadius: 12, padding: spacing.sm },
  audioTextStage: { minHeight: 230, backgroundColor: colors.ink, borderRadius: 14, padding: spacing.lg, justifyContent: "center", marginTop: spacing.sm },
  audioTextNarration: { color: colors.white, fontSize: 20, lineHeight: 30, fontWeight: "700", marginTop: spacing.md },
  playerToolbar: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xs, marginTop: spacing.md },
  playerToolButton: { borderWidth: 1, borderColor: colors.border, borderRadius: 10, paddingHorizontal: spacing.sm, paddingVertical: spacing.sm },
  dockHeading: { color: colors.ink, fontSize: 14, fontWeight: "900", marginTop: spacing.lg },
  styleDock: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xs, marginTop: spacing.sm },
  dockStyleButton: { borderWidth: 1, borderColor: colors.border, backgroundColor: colors.cream, borderRadius: 12, paddingHorizontal: spacing.sm, paddingVertical: spacing.sm },
  selectedDockStyleButton: { borderColor: colors.teal, backgroundColor: colors.mist },
  dockStyleLabel: { color: colors.ink, fontSize: 12, fontWeight: "800" },
  studyHubCard: { backgroundColor: colors.lavender, borderRadius: 18, padding: spacing.md, marginTop: spacing.lg },
  glossaryRow: { borderBottomWidth: 1, borderBottomColor: colors.border, paddingVertical: spacing.sm },
  recommendationNote: { color: colors.tealDark, fontSize: 12, lineHeight: 18, fontWeight: "800", backgroundColor: colors.mist, borderRadius: 10, padding: spacing.sm, marginTop: spacing.sm },
  zoomBackdrop: { flex: 1, backgroundColor: "rgba(8, 19, 28, 0.96)", alignItems: "center", justifyContent: "center", padding: spacing.md },
  zoomImage: { width: "100%", height: "82%" },
  zoomText: { color: colors.white, fontSize: 20, lineHeight: 30, padding: spacing.lg },
  zoomClose: { color: colors.white, marginTop: spacing.md, fontSize: 12 },
  slideshowStyleLabel: { alignSelf: "flex-start", color: colors.tealDark, backgroundColor: colors.mist, borderRadius: 10, paddingHorizontal: spacing.sm, paddingVertical: spacing.xs, fontSize: 11, fontWeight: "800", marginTop: spacing.sm },
  slideHeading: { color: colors.ink, fontSize: 19, fontWeight: "900", marginTop: spacing.md },
  slideControls: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.sm },
  slideControlButton: { flex: 1 },
  loadingIndicator: { marginTop: spacing.md },
  videoSceneLabel: { color: colors.gold, fontSize: 11, fontWeight: "900", letterSpacing: 1.2 },
  videoPlay: { color: colors.teal, fontSize: 56, marginVertical: spacing.md },
  videoSubtitle: { color: colors.white, fontSize: 14, lineHeight: 21, textAlign: "center" },
  sceneCard: { backgroundColor: colors.surface, borderRadius: 16, padding: spacing.md, flexDirection: "row", alignItems: "center", marginBottom: spacing.sm, borderWidth: 1, borderColor: colors.border },
  activeSceneCard: { backgroundColor: colors.lavender, borderColor: colors.teal },
  sceneNumber: { width: 34, height: 34, borderRadius: 17, backgroundColor: colors.teal, color: colors.white, textAlign: "center", lineHeight: 34, fontWeight: "900" },
  paymentTiles: { gap: spacing.sm, marginBottom: spacing.md },
  paymentTile: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 14, padding: spacing.md },
  selectedPaymentTile: { backgroundColor: colors.mist, borderColor: colors.teal },
  paymentTileText: { color: colors.ink, fontSize: 14, fontWeight: "800" },
  sandboxBadge: { backgroundColor: colors.lavender, borderRadius: 12, padding: spacing.sm, marginBottom: spacing.sm },
  sandboxBadgeText: { color: colors.tealDark, fontSize: 12, fontWeight: "800", textAlign: "center" },
  accountStatus: { color: colors.muted, fontSize: 12, fontWeight: "700", marginBottom: spacing.md },
  securityCard: { backgroundColor: colors.lavender, borderRadius: 16, padding: spacing.md, marginBottom: spacing.md },
  modalBackdrop: { flex: 1, backgroundColor: "rgba(18, 35, 42, 0.62)", alignItems: "center", justifyContent: "center", padding: spacing.lg },
  processingCard: { width: "100%", backgroundColor: colors.surface, borderRadius: 22, padding: spacing.xl, alignItems: "center" },
  successModalCard: { width: "100%", backgroundColor: colors.surface, borderRadius: 22, padding: spacing.lg, alignItems: "center" },
  successEmoji: { fontSize: 42, marginBottom: spacing.sm },
  modalTitle: { color: colors.ink, fontSize: 18, fontWeight: "900", textAlign: "center", marginTop: spacing.md },
  modalBody: { color: colors.inkSoft, fontSize: 13, lineHeight: 20, textAlign: "center", marginTop: spacing.sm },
  progressRing: { width: 80, height: 80, borderRadius: 40, borderWidth: 8, borderColor: colors.teal, alignItems: "center", justifyContent: "center" },
  progressValue: { color: colors.ink, fontSize: 17, fontWeight: "800" },
  progressCaption: { color: colors.muted, fontSize: 9, marginTop: 2 },
  headerRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: spacing.lg },
  greeting: { color: colors.ink, fontSize: 24, fontWeight: "800", letterSpacing: -0.4 },
  headerSubtext: { color: colors.inkSoft, fontSize: 15, marginTop: 5 },
  avatar: { width: 44, height: 44, borderRadius: 22, backgroundColor: colors.gold, alignItems: "center", justifyContent: "center" },
  avatarText: { color: colors.ink, fontSize: 18, fontWeight: "800" },
  heroCard: { backgroundColor: colors.ink, borderRadius: 26, padding: spacing.lg, flexDirection: "row", overflow: "hidden", marginBottom: spacing.md },
  heroCopy: { flex: 1 },
  heroKicker: { color: colors.gold, fontSize: 11, fontWeight: "800", letterSpacing: 1.2 },
  heroTitle: { color: colors.white, fontSize: 26, lineHeight: 31, fontWeight: "800", marginTop: 10, maxWidth: 230 },
  heroBody: { color: "#C9D9DE", fontSize: 14, lineHeight: 21, marginTop: 10, maxWidth: 230 },
  heroSpark: { color: colors.teal, fontSize: 64, position: "absolute", right: 12, top: 10, opacity: 0.75 },
  primaryButton: { alignSelf: "flex-start", backgroundColor: colors.teal, borderRadius: 12, paddingHorizontal: 15, paddingVertical: 12, marginTop: 18 },
  primaryButtonText: { color: colors.white, fontSize: 13, fontWeight: "800" },
  statsRow: { flexDirection: "row", gap: spacing.sm, marginBottom: spacing.xl },
  statCard: { flex: 1, backgroundColor: colors.surface, borderRadius: 16, padding: spacing.md, borderWidth: 1, borderColor: colors.border },
  statNumber: { color: colors.ink, fontSize: 22, fontWeight: "800" },
  statLabel: { color: colors.muted, fontSize: 11, marginTop: 4 },
  sectionRow: { flexDirection: "row", alignItems: "flex-end", justifyContent: "space-between", marginBottom: spacing.md },
  sectionTitle: { marginBottom: spacing.sm },
  eyebrow: { color: colors.tealDark, fontSize: 11, fontWeight: "800", letterSpacing: 1.1, marginBottom: 5 },
  sectionHeading: { color: colors.ink, fontSize: 21, fontWeight: "800", letterSpacing: -0.3 },
  linkText: { color: colors.tealDark, fontSize: 13, fontWeight: "800", paddingBottom: 3 },
  lessonCard: { backgroundColor: colors.surface, borderRadius: 18, padding: spacing.md, flexDirection: "row", alignItems: "center", borderWidth: 1, borderColor: colors.border, marginBottom: spacing.xl },
  lessonIcon: { width: 46, height: 46, borderRadius: 14, backgroundColor: "#DFF1EE", alignItems: "center", justifyContent: "center" },
  lessonIconText: { color: colors.tealDark, fontSize: 11, fontWeight: "800" },
  lessonDetails: { flex: 1, marginLeft: spacing.md },
  lessonTitle: { color: colors.ink, fontSize: 15, fontWeight: "800" },
  lessonMeta: { color: colors.muted, fontSize: 12, marginTop: 5, lineHeight: 18 },
  progressTrack: { height: 5, borderRadius: 3, backgroundColor: colors.mist, marginTop: 9, overflow: "hidden" },
  progressFill: { height: 5, borderRadius: 3, backgroundColor: colors.teal },
  chevron: { color: colors.inkSoft, fontSize: 26, paddingLeft: 8 },
  questionCard: { backgroundColor: colors.lavender, borderRadius: 18, padding: spacing.md, flexDirection: "row", alignItems: "center" },
  questionBadge: { width: 44, height: 44, borderRadius: 14, backgroundColor: colors.coral, alignItems: "center", justifyContent: "center" },
  questionBadgeText: { color: colors.white, fontSize: 19, fontWeight: "800" },
  pageIntro: { color: colors.inkSoft, fontSize: 15, lineHeight: 22, marginBottom: spacing.lg },
  uploadCard: { borderWidth: 1.5, borderColor: colors.teal, borderStyle: "dashed", borderRadius: 18, padding: spacing.md, flexDirection: "row", alignItems: "center", marginBottom: spacing.md },
  uploadIcon: { width: 44, height: 44, borderRadius: 14, backgroundColor: colors.mist, color: colors.tealDark, fontSize: 27, textAlign: "center", lineHeight: 42, marginRight: spacing.md },
  libraryRow: { backgroundColor: colors.surface, borderRadius: 16, padding: spacing.md, flexDirection: "row", alignItems: "center", marginBottom: spacing.sm, borderWidth: 1, borderColor: colors.border },
  downloaded: { color: colors.success, fontSize: 18, fontWeight: "800" },
  focusCard: { backgroundColor: colors.surface, borderRadius: 24, padding: spacing.lg, borderWidth: 1, borderColor: colors.border, marginTop: spacing.sm },
  focusTop: { flexDirection: "row", justifyContent: "space-between" },
  focusLabel: { color: colors.coral, fontSize: 11, fontWeight: "800", letterSpacing: 1 },
  focusCount: { color: colors.muted, fontSize: 12 },
  puzzlePrompt: { color: colors.ink, fontSize: 20, fontWeight: "800", marginTop: spacing.xl, textAlign: "center" },
  sequence: { color: colors.tealDark, fontSize: 23, fontWeight: "800", textAlign: "center", marginVertical: spacing.lg },
  answerRow: { flexDirection: "row", gap: spacing.sm },
  answerButton: { flex: 1, borderWidth: 1, borderColor: colors.border, borderRadius: 14, paddingVertical: 14, alignItems: "center" },
  correctAnswer: { backgroundColor: colors.mist, borderColor: colors.teal },
  answerText: { color: colors.ink, fontSize: 16, fontWeight: "800" },
  successText: { color: colors.success, textAlign: "center", fontSize: 13, fontWeight: "700", marginTop: spacing.md },
  retryText: { color: colors.coral, textAlign: "center", fontSize: 13, fontWeight: "700", marginTop: spacing.md },
  tipCard: { flexDirection: "row", backgroundColor: "#FFF3DD", borderRadius: 18, padding: spacing.md, marginTop: spacing.md },
  tipIcon: { color: colors.coral, fontSize: 24, marginRight: spacing.sm },
  tipCopy: { flex: 1 },
  tipTitle: { color: colors.ink, fontWeight: "800", fontSize: 14, marginBottom: 3 },
  practiceCard: { backgroundColor: colors.surface, borderRadius: 20, padding: spacing.lg, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.md },
  practiceHeader: { flexDirection: "row", justifyContent: "space-between" },
  practiceTag: { color: colors.coral, fontSize: 10, fontWeight: "800", letterSpacing: 1 },
  practiceDots: { color: colors.muted, letterSpacing: 2 },
  practiceQuestion: { color: colors.ink, fontSize: 18, lineHeight: 26, fontWeight: "700", marginVertical: spacing.lg },
  recallChoice: { borderWidth: 1, borderColor: colors.border, borderRadius: 12, padding: spacing.md, marginTop: spacing.sm },
  selectedRecallChoice: { borderColor: colors.teal, backgroundColor: colors.mist },
  outlineButton: { borderWidth: 1, borderColor: colors.teal, borderRadius: 12, paddingVertical: 12, alignItems: "center" },
  outlineButtonText: { color: colors.tealDark, fontSize: 13, fontWeight: "800" },
  aiInput: { minHeight: 150, backgroundColor: colors.surface, borderRadius: 18, borderWidth: 1, borderColor: colors.border, padding: spacing.md, color: colors.ink, fontSize: 15, textAlignVertical: "top", marginBottom: spacing.sm },
  languageInput: { backgroundColor: colors.surface, borderRadius: 14, borderWidth: 1, borderColor: colors.border, padding: spacing.md, color: colors.ink, fontSize: 15, marginBottom: spacing.sm },
  formatRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, marginBottom: spacing.md },
  formatButton: { borderWidth: 1, borderColor: colors.border, borderRadius: 12, paddingHorizontal: 12, paddingVertical: 9 },
  selectedFormat: { backgroundColor: colors.mist, borderColor: colors.teal },
  formatText: { color: colors.inkSoft, fontSize: 12, fontWeight: "700" },
  selectedFormatText: { color: colors.tealDark },
  errorText: { color: colors.coral, fontSize: 13, lineHeight: 19, marginTop: spacing.md },
  resultCard: { backgroundColor: colors.surface, borderRadius: 18, borderWidth: 1, borderColor: colors.border, padding: spacing.md, marginTop: spacing.lg },
  resultLabel: { color: colors.tealDark, fontSize: 10, fontWeight: "800", letterSpacing: 1 },
  resultText: { color: colors.ink, fontSize: 15, lineHeight: 23, marginTop: spacing.sm },
  tabBar: { position: "absolute", left: 0, right: 0, bottom: 0, height: 82, backgroundColor: colors.surface, borderTopWidth: 1, borderTopColor: colors.border, flexDirection: "row", justifyContent: "space-around", paddingTop: 12 },
  tabItem: { alignItems: "center", minWidth: 64 },
  tabIcon: { color: colors.muted, fontSize: 22, height: 27 },
  tabLabel: { color: colors.muted, fontSize: 11, fontWeight: "700", marginTop: 3 },
  activeTab: { color: colors.tealDark },
});
