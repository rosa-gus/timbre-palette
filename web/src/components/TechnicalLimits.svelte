<script lang="ts">
</script>

<details class="technical-limits">
  <summary>Limites técnicos</summary>
  <div class="limits-content">
    <p class="limits-intro">Uma leitura aproximada da sua escuta.</p>
    <p>
      A paleta combina seu histórico público do Last.fm com créditos instrumentais
      publicados. Não analisa o áudio das músicas nem mede o volume dos instrumentos.
    </p>
    <p>
      Um instrumento pode estar presente na música sem estar documentado nos créditos
      da gravação no MusicBrainz. Encontrar a gravação nessa base não garante encontrar
      seus instrumentos. Essa documentação varia entre repertórios, por isso uma
      ausência na paleta não significa ausência na música.
    </p>
    <p>
      O catálogo ainda está em construção: faixas sem evidência instrumental aceita
      não entram no cálculo. Novas evidências podem alterar o resultado em uma
      visita futura.
    </p>
    <p>
      O temperamento da escuta é uma interpretação editorial e lúdica. Não é uma
      avaliação psicológica ou científica da sua personalidade.
    </p>
  </div>
</details>

<style>
  .technical-limits {
    margin-top: 24px;
    color: var(--muted);
  }
  summary {
    display: flex;
    align-items: center;
    gap: 10px;
    min-height: 44px;
    width: fit-content;
    padding: 10px 0;
    font-family: var(--meta);
    font-size: 12px;
    line-height: 1.5;
    list-style: none;
    cursor: pointer;
  }
  summary::-webkit-details-marker { display: none; }
  summary::before { content: "▸"; }
  .technical-limits[open] > summary::before { content: "▾"; }
  summary:hover { color: var(--ink); }
  summary:focus-visible {
    outline: 2px solid var(--accent-soft);
    outline-offset: 4px;
  }
  .limits-content {
    max-width: 680px;
    border-left: 1px solid var(--line-strong);
    padding: 4px 0 16px 20px;
    font-size: 13px;
    line-height: 1.7;
  }
  p { margin: 0 0 12px; }
  p:last-child { margin-bottom: 0; }
  .limits-intro { color: var(--ink); }
</style>
