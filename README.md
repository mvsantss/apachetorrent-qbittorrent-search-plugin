# ApacheTorrent Search Plugin for qBittorrent

Plugin de busca para usar o ApacheTorrent na aba `Buscar` do qBittorrent.

- `apachetorrent.py`

Use apenas para pesquisar conteudo que voce tem direito de acessar no seu pais.

## Melhorias desta versao

- Codigo organizado em constantes, parsers e funcoes auxiliares.
- Autor atualizado para `mvsantss`.
- Comentarios nas partes mais sensiveis do parser.
- Limite global de resultados para evitar buscas lentas.
- Deduplicacao por link de detalhe e hash magnet.
- Filtro basico por categoria: filmes, series e anime/desenho.
- Extracao de tamanho, qualidade, idioma e formato quando a pagina informa.
- Fallback para DNS publico quando o DNS da maquina aponta o dominio para pagina de bloqueio.
- Fallback de conexao HTTPS direta com SNI correto quando o helper do qBittorrent falha por SSL.
- A busca lista os cards imediatamente; o link magnet e resolvido apenas ao solicitar o download.
- A busca detalhada tenta preencher tamanho, data de publicacao e link magnet diretamente nos resultados.
- Seeders e leechers ficam como desconhecidos porque o ApacheTorrent nao publica estes numeros.

## Instalar pelo arquivo local

1. Abra o qBittorrent.
2. Ative a aba de busca em `Exibir > Motor de busca`.
3. Abra a aba `Buscar`.
4. Clique em `Plugins de busca...`.
5. Clique em `Instalar novo plugin`.
6. Selecione o arquivo `apachetorrent.py`.
7. Pesquise usando o motor `ApacheTorrent`.

## Instalar pela URL Raw do GitHub

No qBittorrent:

1. Abra `Buscar > Plugins de busca...`.
2. Clique em `Instalar novo plugin`.
3. Cole a URL `raw.githubusercontent.com` do arquivo `apachetorrent.py`.
4. Confirme.

## Publicar no GitHub manualmente

1. Crie uma conta ou entre em https://github.com.
2. Crie um repositorio novo, por exemplo `qbittorrent-apachetorrent-plugin`.
3. Envie o arquivo `apachetorrent.py` para o repositorio.
4. Abra o arquivo no GitHub.
5. Clique em `Raw`.
6. Copie a URL da pagina `Raw`.

A URL deve ficar parecida com:

```text
https://raw.githubusercontent.com/SEU_USUARIO/qbittorrent-apachetorrent-plugin/main/apachetorrent.py
```

Quando voce atualizar o arquivo no GitHub, abra a janela de plugins do qBittorrent e clique em `Procurar atualizacoes`.

## Publicar usando Git pelo terminal

Dentro da pasta onde esta o arquivo `apachetorrent.py`, rode:

```powershell
git init
git add apachetorrent.py README-apachetorrent.md
git commit -m "Add ApacheTorrent qBittorrent search plugin"
git branch -M main
git remote add origin https://github.com/SEU_USUARIO/qbittorrent-apachetorrent-plugin.git
git push -u origin main
```

Troque `SEU_USUARIO` pelo seu usuario do GitHub.
