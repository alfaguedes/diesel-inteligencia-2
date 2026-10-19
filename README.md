# Diesel Inteligência

Painel de preços oficiais de revenda de diesel S10 e S500 no Brasil.

- Não inclui preços fictícios.
- O workflow verifica diariamente a página de dados abertos da ANP; a pesquisa pode ser semanal, então verificar diariamente não significa que os preços sejam publicados diariamente.
- Fonte: https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/serie-historica-de-precos-de-combustiveis
- Notícias e cotações B2B de distribuidores ainda precisam de integrações adicionais.
- O primeiro download precisa ser validado nos logs do GitHub Actions, pois a ANP pode alterar o formato dos CSVs.
- Para publicar, envie toda esta estrutura à raiz do repositório, configure Settings → Pages → GitHub Actions e execute o workflow manualmente.
