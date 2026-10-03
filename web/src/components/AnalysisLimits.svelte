<script lang="ts">
  import Dropdown from "./Dropdown.svelte";
</script>

<Dropdown title="Limites da análise">
  <p class="limits-intro">Uma leitura aproximada da sua escuta.</p>
  <p>
    A paleta combina seu histórico público do Last.fm com créditos
    instrumentais publicados. Não analisa o áudio das músicas nem mede o
    volume dos instrumentos.
  </p>
  <p>
    Um instrumento pode estar presente na música sem estar documentado
    nos créditos da gravação no MusicBrainz. Encontrar a gravação nessa
    base não garante encontrar seus instrumentos. Essa documentação
    varia entre repertórios, por isso uma ausência na paleta não
    significa ausência na música.
  </p>
  <p>
    Faixas sem créditos instrumentais suficientes ficam fora do cálculo
    da paleta. Artistas pouco conhecidos e parte da música atual,
    sobretudo a produzida com software, podem ter menos créditos
    publicados: sons programados, sintetizados ou sampleados nem sempre
    são registrados como instrumentos.
  </p>
  <p>
    O catálogo pode receber novos dados, então uma consulta futura pode
    trazer outro resultado, sem garantia de identificar mais
    instrumentos.
  </p>
  <p>
    O vocabulário dos artistas reúne instrumentos documentados em
    gravações desses artistas; não confirma que estejam nas músicas que
    você ouviu.
  </p>
  <p>
    O temperamento da escuta é uma interpretação editorial e lúdica. Não
    é uma avaliação psicológica ou científica da sua personalidade.
  </p>
</Dropdown>

<style>
  .limits-intro {
    color: var(--ink);
  }
</style>
