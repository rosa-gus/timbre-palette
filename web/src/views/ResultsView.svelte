<script lang="ts">
  import { Tabs } from "bits-ui";
  import { normalizePathname } from "../navigation";
  import { getAsciiLines, hasAsciiDrawing } from "../sharing/ascii";
  import Arrow from "../components/Arrow.svelte";
  import Dropdown from "../components/Dropdown.svelte";
  import type {
    AnalysisStatus,
    AnalysisView,
    Confidence,
    ProfileAnalysisV2,
    SectionAvailability,
  } from "../api/types";
  import ReportView from "./ReportView.svelte";

  type SectionId = "portrait" | "palette" | "discovery" | "share";
  type SectionOption = { value: string; label: string; disabled?: boolean; note?: string };
  export let result: ProfileAnalysisV2;
  export let activeView: AnalysisView;
  export let onSelectView: (view: AnalysisView) => void;
  export let sectionOptions: SectionOption[] = [];
  export let periodLabels: Record<string, string>;
  export let statusLabels: Record<AnalysisStatus, string>;
  export let confidenceLabels: Record<Confidence, string>;
  export let shareFeedback = "";
  export let sharePreviewUrl = "";
  export let shareBusy = false;
  export let onDownloadShare: () => void;
  export let onOpenInstrument: () => void;
  export let onOpenInstrumentSlug: (slug: string) => void;
  export let onGenerateShare: () => void;
  export let getAvailability: (section: SectionId) => SectionAvailability;

  const homePath = normalizePathname();
  $: palette = result.track_palette;
  $: vocabulary = result.artist_vocabulary;
  $: predominantFamily = vocabulary.families.reduce<(typeof vocabulary.families)[number] | null>(
    (highest, family) => !highest || family.score > highest.score ? family : highest,
    null,
  );
  $: predominantDrawing = vocabulary.status === "available" && predominantFamily &&
    hasAsciiDrawing(predominantFamily.slug)
    ? getAsciiLines(predominantFamily.slug).join("\n")
    : null;
  $: directAvailable = palette.analysis.status !== "insufficient" &&
    palette.analysis.section_availability.families === "available";
  $: lastFmUrl = result.profile.profile_url ??
    `https://www.last.fm/user/${encodeURIComponent(result.profile.username)}`;

  function percent(value: number): string {
    return `${Math.round(value * 100)}%`;
  }
  function count(value: number): string {
    return value.toLocaleString("pt-BR");
  }
  function lastFmAvatarFallbackUrl(source: string): string | null {
    try {
      const url = new URL(source);
      if (url.hostname !== "lastfm-img.freetls.fastly.net") return null;
      if (!/\/i\/u\//.test(url.pathname) || !/\.png$/i.test(url.pathname)) return null;
      url.hostname = "lastfm.freetls.fastly.net";
      url.pathname = url.pathname.replace(/\.png$/i, ".gif");
      return url.toString();
    } catch {
      return null;
    }
  }
  function handleAvatarError(event: Event): void {
    const image = event.currentTarget as HTMLImageElement;
    const fallback = lastFmAvatarFallbackUrl(image.src);
    if (fallback && image.src !== fallback) image.src = fallback;
  }
  function vocabularyLabel(): string {
    if (vocabulary.status === "available") return "disponível";
    if (vocabulary.status === "pending") return "em preparação";
    return "insuficiente";
  }
  function reasonText(reason: string): string {
    const reasons: Record<string, string> = {
      no_mapped_evidence: "Ainda não há instrumentos recorrentes documentados para esta leitura.",
      insufficient_track_reach: "Os artistas qualificados ainda representam poucas faixas deste histórico.",
      insufficient_play_reach: "Os artistas qualificados ainda representam poucas reproduções deste histórico.",
      insufficient_artist_diversity: "Ainda há poucos artistas qualificados para uma leitura diversa.",
      excessive_artist_concentration: "A evidência está concentrada demais em um único artista.",
    };
    return reasons[reason] ?? "Ainda não há evidência suficiente para apresentar esta leitura.";
  }
  function handleTabChange(value: string): void {
    if (value === "track_palette" || value === "artist_vocabulary") {
      onSelectView(value);
    }
  }
</script>

<div class="results-view">
  <a class="back-link" href={homePath}><Arrow direction="left" />VOLTAR</a>
  <section class="profile-card" aria-labelledby="profile-title">
    <div class="profile-avatar">
      {#if result.profile.avatar_url}
        <img
          src={result.profile.avatar_url}
          alt={`Foto de perfil de @${result.profile.username}`}
          on:error={handleAvatarError}
        />
      {:else}
        <span aria-hidden="true">[ ? ? ? ]</span>
      {/if}
    </div>
    <div class="profile-copy">
      <div class="profile-identity">
        <p class="eyebrow">PERFIL LAST.FM</p>
        <h1 id="profile-title">{result.profile.realname || `@${result.profile.username}`}</h1>
        {#if result.profile.realname}<p class="profile-username">@{result.profile.username}</p>{/if}
      </div>
      <div class="profile-footer">
        <div class="profile-meta">
          <span>ANÁLISE {periodLabels[result.profile.period]}</span>
          {#if palette.analysis.data_source !== "catalog"}
            <span>{palette.analysis.data_source === "mock" ? "dados demonstrativos" : "dados híbridos"}</span>
          {/if}
        </div>
        <a class="profile-link" href={lastFmUrl} target="_blank" rel="noreferrer">
          VER NO LAST.FM <Arrow direction="up-right" />
        </a>
      </div>
    </div>
  </section>

  <Tabs.Root
    value={activeView}
    onValueChange={handleTabChange}
    activationMode="manual"
    orientation="horizontal"
    loop
    class="view-tabs"
  >
    <Tabs.List class="view-switch" aria-label="Leituras da escuta">
      <Tabs.Trigger value="track_palette" class="view-tab view-tab-palette">
      <span>01 / PALETA DAS FAIXAS</span>
      <small>{statusLabels[palette.analysis.status]}</small>
      </Tabs.Trigger>
      <Tabs.Trigger value="artist_vocabulary" class="view-tab view-tab-vocabulary">
      <span>02 / VOCABULÁRIO DOS ARTISTAS</span>
      <small>{vocabularyLabel()}</small>
      </Tabs.Trigger>
    </Tabs.List>

  <Tabs.Content value="track_palette" class="view-panel">
    {#if directAvailable}
      <ReportView report={palette} embedded {sectionOptions} {periodLabels}
        {statusLabels} {confidenceLabels} {shareFeedback} {sharePreviewUrl}
        {shareBusy} {onDownloadShare} {onOpenInstrument} {onGenerateShare}
        {getAvailability} hydrationPending={result.hydration.status === "pending"} />
    {:else}
      <section class="unavailable-reading" aria-labelledby="direct-title">
        <p class="eyebrow">01 / PALETA DAS FAIXAS · INSUFICIENTE</p>
        <h2 id="direct-title">Ainda não há um retrato das suas faixas.</h2>
        <p>Não encontramos créditos instrumentais diretos aceitos em uma amostra suficiente deste histórico. Isso não significa que esses instrumentos estejam ausentes das músicas.</p>
        <p class="reading-measure">{percent(palette.analysis.coverage_tracks)} das faixas · {percent(palette.analysis.coverage_plays)} das reproduções cobertas</p>
        {#if vocabulary.status === "available"}<button type="button" on:click={() => onSelectView("artist_vocabulary")}>VER VOCABULÁRIO DOS ARTISTAS →</button>{/if}
      </section>
    {/if}
  </Tabs.Content>
  <Tabs.Content value="artist_vocabulary" class="view-panel">
    <section class="vocabulary-reading" aria-labelledby="vocabulary-title">
      <div class="vocabulary-lead">
        <div>
          <p class="eyebrow">02 / VOCABULÁRIO DOS ARTISTAS · {vocabularyLabel().toUpperCase()}</p>
          <h2 id="vocabulary-title">Os sons documentados ao redor dos artistas.</h2>
          <p class="lead-copy">Instrumentos que recorrem em gravações documentadas dos artistas presentes na sua escuta.</p>
          <p class="scope-note">{vocabulary.notice}</p>
        </div>
        {#if predominantDrawing && predominantFamily}
          <figure class="type-art" aria-label={`Desenho ASCII da família ${predominantFamily.name}, predominante no vocabulário`}>
            <pre aria-hidden="true">{predominantDrawing}</pre>
            <figcaption>{predominantFamily.name} / família predominante</figcaption>
          </figure>
        {/if}
      </div>

      {#if vocabulary.status === "available"}
        <div class="reach-grid" aria-label="Alcance do vocabulário">
          <div><span>FAIXAS LIGADAS A ARTISTAS QUALIFICADOS</span><strong>{count(vocabulary.reach.qualified_tracks)} / {count(vocabulary.reach.total_tracks)}</strong><small>{percent(vocabulary.reach.track_reach)} das faixas</small></div>
          <div><span>REPRODUÇÕES</span><strong>{percent(vocabulary.reach.play_reach)}</strong><small>{count(vocabulary.reach.qualified_plays)} / {count(vocabulary.reach.total_plays)} reproduções</small></div>
          <div><span>ARTISTAS QUALIFICADOS</span><strong>{count(vocabulary.reach.qualified_artists)} / {count(vocabulary.reach.total_artists)}</strong><small>com instrumentos recorrentes</small></div>
        </div>
        <div class="family-heading"><span>FAMÍLIAS NO VOCABULÁRIO</span><span>PARTICIPAÇÃO NO MODELO</span></div>
        <div class="vocabulary-families">
          {#each vocabulary.families as family, index}
            <article class="vocabulary-family">
              <div class="family-top"><span class="family-index">{String(index + 1).padStart(2, "0")}</span><h3>{family.name}</h3><strong>{percent(family.share)}</strong></div>
              <div class="vocabulary-bar" role="img" aria-label={`${family.name}: ${percent(family.share)} de participação no modelo`}><span style={`width:${family.share * 100}%`}></span></div>
              <p>{count(family.supporting_artists)} {family.supporting_artists === 1 ? "artista com suporte" : "artistas com suporte"} · {family.instruments.map((instrument) => instrument.name).join(", ")}</p>
              <div class="family-evidence">
                <Dropdown title="Critérios e evidências">
                  <p>Os instrumentos abaixo recorrem em pelo menos três gravações distintas documentadas de um artista. Eles não são créditos atribuídos às faixas deste histórico.</p>
                  <ul>{#each family.instruments as instrument}<li><button type="button" class="instrument-link" on:click={() => onOpenInstrumentSlug(instrument.slug)}>{instrument.name} ↗</button><span>{count(instrument.distinct_recordings)} gravações distintas · crédito de {instrument.evidence.scope === "track" ? "faixa" : "gravação"}</span></li>{/each}</ul>
                </Dropdown>
              </div>
            </article>
          {/each}
        </div>
      {:else}
        <div class="vocabulary-state" role="status">
          <span aria-hidden="true">[ * . . ]</span>
          <h3>{vocabulary.status === "pending" ? "Esta leitura ainda está em preparação." : "Ainda não há um vocabulário para mostrar."}</h3>
          <p>{vocabulary.status === "pending" ? "Estamos reunindo informações sobre artistas deste histórico. Isso pode levar horas; volte mais tarde para consultar novamente." : reasonText(vocabulary.availability.reason)}</p>
        </div>
      {/if}

      {#if vocabulary.status === "available"}
        <div class="vocabulary-method">
          <Dropdown title="O que estes números significam">
            <p>O alcance mostra a parte do histórico ligada a artistas com instrumentos recorrentes documentados. Ele não é a cobertura da paleta das faixas.</p>
            <p>A participação mostra o peso relativo calculado entre as famílias deste vocabulário. Não mede volume, duração ou presença do instrumento nas faixas ouvidas.</p>
            <p>Maior contribuição de um único artista para a pontuação: {percent(vocabulary.concentration)}.</p>
            <p>{count(vocabulary.reach.unresolved_artists)} artistas e {count(vocabulary.reach.unresolved_tracks)} faixas sem identidade MusicBrainz não entram na consulta pendente.</p>
            <p>Snapshot MusicBrainz {result.snapshot.snapshot_version} · Método do vocabulário {vocabulary.methodology_version}</p>
          </Dropdown>
        </div>
      {/if}
    </section>
  </Tabs.Content>
  </Tabs.Root>
</div>

<style>
  .results-view { width:100%; max-width:1320px; margin:0 auto; padding:54px 0 32px; }
  .back-link { display:inline-block; margin-bottom:28px; color:var(--accent-soft); font:13px var(--meta); letter-spacing:.06em; text-decoration:none; }
  .back-link:hover { color:var(--ink); }
  .eyebrow { font:12px var(--meta); letter-spacing:.07em; line-height:1.6; }
  .eyebrow { color:var(--muted); }
  .profile-card { display:grid; grid-template-columns:120px minmax(0,1fr); align-items:stretch; gap:24px; padding:0 0 24px; margin-bottom:38px; border-bottom:1px solid var(--line-strong); }
  .profile-avatar { display:grid; width:120px; aspect-ratio:1; overflow:hidden; place-items:center; background:var(--panel); color:var(--accent-soft); font:13px var(--meta); }
  .profile-avatar img { display:block; width:100%; height:100%; border:1px solid var(--line-strong); object-fit:cover; }
  .profile-copy { display:flex; min-width:0; flex-direction:column; justify-content:space-between; gap:24px; }
  .profile-identity .eyebrow { margin:0; }
  .profile-identity h1 { margin:6px 0 0; color:var(--ink); font-size:clamp(1.8rem,2.6vw,2.6rem); line-height:1.1; overflow-wrap:anywhere; }
  .profile-username { margin:6px 0 0; color:var(--muted); font:14px var(--meta); overflow-wrap:anywhere; }
  .profile-footer { display:flex; align-items:end; justify-content:space-between; flex-wrap:wrap; gap:16px 24px; }
  .profile-meta { display:flex; flex-wrap:wrap; gap:8px 18px; color:var(--quiet); font:12px var(--meta); letter-spacing:.05em; text-transform:uppercase; }
  .profile-link { display:inline-flex; align-items:center; min-height:40px; padding:8px 12px; border:1px solid var(--line-strong); color:var(--muted); font:12px var(--meta); letter-spacing:.04em; text-decoration:none; white-space:nowrap; }
  .profile-link:hover, .profile-link:focus-visible { border-color:var(--accent-soft); color:var(--accent-soft); }
  :global(.view-tabs) { width:100%; }
  :global(.view-switch) { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); border-top:1px solid var(--line-strong); border-bottom:1px solid var(--line-strong); }
  :global(.view-tab) { position:relative; z-index:0; display:flex; align-items:center; justify-content:space-between; gap:16px; min-height:76px; padding:20px 24px; border:0; border-bottom:3px solid transparent; border-radius:0; background:transparent; color:var(--muted); cursor:pointer; text-align:left; font:13px var(--meta); letter-spacing:.04em; transition:background-color 150ms ease, border-color 150ms ease, color 150ms ease; }
  :global(.view-tab + .view-tab) { border-left:1px solid var(--line); }
  :global(.view-tab:hover), :global(.view-tab:focus-visible) { color:var(--ink); }
  :global(.view-tab-palette) { border-left:1px solid var(--line-strong); border-right:1px solid var(--line); }
  :global(.view-tab-vocabulary) { border-left:1px solid var(--line); border-right:1px solid var(--line-strong); }
  :global(.view-tab[data-state="active"]) { z-index:1; border-top:0; border-bottom:3px solid var(--accent); background:var(--panel); color:var(--ink); }
  :global(.view-tab small) { color:var(--accent-soft); font:12px var(--meta); white-space:nowrap; }
  .unavailable-reading button { margin-left:auto; padding:10px 12px; border:1px solid var(--line-strong); border-radius:0; background:transparent; color:var(--ink); cursor:pointer; font:12px var(--meta); white-space:nowrap; }
  button:hover:not(:disabled) { border-color:var(--accent-soft); color:var(--accent-soft); }
  button:disabled { opacity:.6; cursor:default; }
  .unavailable-reading { max-width:760px; padding:68px 0 100px; }
  .unavailable-reading h2, .vocabulary-lead h2 { margin:12px 0 18px; font-size:clamp(2rem,3.8vw,3.6rem); line-height:1.08; }
  .unavailable-reading > p:not(.eyebrow), .lead-copy { color:var(--muted); font-size:clamp(1rem,1.3vw,1.18rem); }
  .reading-measure { margin:26px 0; font-family:var(--meta); font-size:13px !important; }
  .unavailable-reading button { margin:12px 0 0; }
  .vocabulary-reading { padding-top:52px; }
  .vocabulary-lead { display:flex; justify-content:space-between; gap:36px; padding-bottom:44px; }
  .vocabulary-lead > div { max-width:790px; }
  .lead-copy { margin:0 0 12px; }
  .scope-note { max-width:630px; color:var(--quiet); font-size:13px; }
  .type-art { align-self:center; margin:0 3vw 0 0; color:var(--accent-soft); }
  .type-art pre { margin:0; font:clamp(11px,1vw,15px)/1.05 var(--meta); white-space:pre; }
  .type-art figcaption { margin-top:16px; color:var(--muted); font:11px var(--meta); letter-spacing:.04em; text-transform:uppercase; }
  .reach-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); border-top:1px solid var(--line-strong); border-bottom:1px solid var(--line-strong); }
  .reach-grid > div { display:flex; flex-direction:column; gap:8px; min-width:0; padding:22px 24px; }
  .reach-grid > div:first-child { padding-left:0; }
  .reach-grid > div + div { border-left:1px solid var(--line); }
  .reach-grid span, .reach-grid small, .family-heading, .family-index { color:var(--muted); font:12px var(--meta); letter-spacing:.05em; }
  .reach-grid strong { font-size:clamp(1.55rem,2.8vw,2.8rem); font-weight:500; line-height:1.1; }
  .family-heading { display:flex; justify-content:space-between; gap:16px; margin:54px 0 8px; }
  .vocabulary-family { padding:24px 0 26px; border-top:1px solid var(--line); }
  .family-top { display:grid; grid-template-columns:40px 1fr auto; align-items:baseline; gap:18px; }
  .family-top h3 { margin:0; font-size:clamp(1.5rem,2.3vw,2.4rem); }
  .family-top strong { font:20px var(--meta); color:var(--accent-soft); }
  .vocabulary-bar { height:11px; margin:20px 0 14px 58px; background:var(--panel); }
  .vocabulary-bar span { display:block; height:100%; background:var(--accent); }
  .vocabulary-family > p { margin:0 0 0 58px; color:var(--muted); font-size:14px; }
  .family-evidence { margin:16px 0 0 58px; }
  .family-evidence p { max-width:650px; }
  .vocabulary-family ul { max-width:760px; margin:14px 0 0; padding:0; list-style:none; }
  .vocabulary-family li { display:flex; justify-content:space-between; gap:16px; padding:8px 0; border-top:1px solid var(--line); }
  .vocabulary-family li span:first-child { color:var(--ink); }
  .instrument-link { padding:0; border:0; background:transparent; color:var(--ink); cursor:pointer; font:inherit; text-align:left; }
  .instrument-link:hover { color:var(--accent-soft); }
  .vocabulary-state { max-width:700px; padding:45px 0 55px; border-top:1px solid var(--line); }
  .vocabulary-state > span { color:var(--accent-soft); font:13px var(--meta); }
  .vocabulary-state h3 { margin:14px 0; font-size:clamp(1.5rem,2.5vw,2.3rem); }
  .vocabulary-state p { color:var(--muted); }
  .vocabulary-method { max-width:850px; margin:50px 0 40px; }
  .vocabulary-method p { max-width:700px; }
  @media(max-width:800px) {
    .results-view { padding-top:32px; }
    .profile-card { grid-template-columns:88px minmax(0,1fr); gap:16px; padding-bottom:20px; }
    .profile-avatar { width:88px; }
    .profile-identity h1 { font-size:clamp(1.6rem,6vw,2.2rem); }
    .profile-copy { gap:18px; }
    :global(.view-switch) { grid-template-columns:1fr; }
    :global(.view-tab) { min-height:60px; padding:14px 10px; }
    :global(.view-tab + .view-tab) { border-top:1px solid var(--line); }
    .vocabulary-reading { padding-top:34px; }
    .vocabulary-lead { flex-direction:column; padding-bottom:28px; }
    .type-art { align-self:flex-start; margin:12px 0 0; }
    .type-art pre { font-size:clamp(9px,2.8vw,13px); }
    .reach-grid { grid-template-columns:1fr; }
    .reach-grid > div, .reach-grid > div:first-child { padding:14px 0; }
    .reach-grid > div + div { border-left:0; border-top:1px solid var(--line); }
    .family-heading { margin-top:40px; }
    .family-heading span:last-child { max-width:125px; text-align:right; }
    .vocabulary-bar, .vocabulary-family > p, .family-evidence { margin-left:0; }
    .family-top { grid-template-columns:26px 1fr auto; gap:10px; }
    .vocabulary-family li { display:grid; gap:2px; }
  }
</style>
