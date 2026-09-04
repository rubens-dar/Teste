# leadhunter — prospecção de vendedores do Mercado Livre

Recebe uma planilha de vendedores do Mercado Livre e devolve, para cada um:
**quem é o dono, WhatsApp, telefone e e-mail** — com a fonte de cada dado registrada.

Feito para vendedores de **Tubarão/SC**, mas a cidade é configurável.

---

## A ideia central

O caminho curto para o contato do dono não passa por raspar o Mercado Livre à força.
Passa por **descobrir o CNPJ** e usar os dados abertos da Receita Federal, que são
públicos e trazem exatamente o que interessa:

```
vendedor no ML  ──▶  CNPJ  ──▶  Receita Federal  ──▶  quadro de sócios (o DONO)
                                                 ├─▶  telefone cadastral
                                                 └─▶  e-mail cadastral
```

Dois detalhes que fazem esse caminho render muito:

- O telefone e o e-mail que constam na Receita foram informados pela própria empresa
  na abertura. Em empresa pequena, quase sempre são **o celular e o e-mail pessoal do dono**.
- **MEI e empresário individual não têm quadro de sócios** — mas a razão social *é* o nome
  do dono (`JOÃO CARLOS DA SILVA 12345678901`). O código detecta esse padrão e extrai o nome.
  Boa parte dos vendedores pequenos do ML cai nesse caso.

O resto do pipeline existe para (a) achar o CNPJ quando ele não está exposto e
(b) achar um contato melhor quando o da Receita está desatualizado.

## Como cada lead é processado

| # | Etapa | O que busca | Precisa de chave? |
|---|---|---|---|
| 1 | **Mercado Livre** | `seller_id` pela API pública; depois raspa o perfil e um anúncio atrás do bloco legal (`razão social` + `CNPJ`) que a plataforma é obrigada a exibir | não |
| 2 | **CNPJ por nome** | se o passo 1 não achou: base local da Receita (ver abaixo) e, como reserva, diretórios de CNPJ via buscador | não |
| 3 | **Receita Federal** | sócios/proprietário, telefone cadastral, e-mail cadastral, endereço, CNAE — via BrasilAPI, com MinhaReceita e CNPJ.ws como reserva | não |
| 4 | **Google Maps** | telefone que a empresa de fato atende, no perfil do Google Business | `GOOGLE_MAPS_KEY` |
| 5 | **Site da empresa** | acha o site pelo buscador e raspa home + `/contato` + `/sobre`: `mailto:`, `tel:`, links `wa.me`, e-mails e telefones no texto | não |
| 6 | **Instagram / LinkedIn** | bio do Instagram (onde loja pequena publica o WhatsApp) e perfil do dono no LinkedIn | não |
| 7 | **Consolidação** | deduplica, normaliza para E.164, promove todo celular a candidato a WhatsApp, pontua e classifica | — |

Todo CNPJ descoberto por nome só é aceito depois de **confirmado na Receita**: o município
tem que ser o da planilha e o nome tem que bater por similaridade. Isso evita o pior erro
possível aqui, que é atribuir o dono errado a um lead.

## Classificação da saída

| Tier | Significado |
|---|---|
| **A** | nome do dono **+ WhatsApp** — pronto para abordagem |
| **B** | nome do dono + telefone ou e-mail |
| **C** | só contato da empresa, sem nome do dono |
| **D** | nada encontrado — vai para `revisao_manual.csv` |

## Instalação

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # opcional: preencha as chaves que tiver
```

## Uso

```bash
# verifica acesso às fontes e quais chaves estão configuradas
python -m leadhunter doctor

# processa a planilha (CSV, XLSX ou link do Google Sheets)
python -m leadhunter enrich data/input/leads.csv

# consulta avulsa de CNPJ, útil para depurar
python -m leadhunter cnpj 03.361.252/0001-34
```

Saídas em `data/output/`:

- `leads_enriquecidos.xlsx` / `.csv` — a planilha final
- `revisao_manual.csv` — só os leads que precisam de olho humano
- `evidencias.json` — trilha completa: cada dado, sua fonte, a URL e a confiança

A planilha de entrada não precisa de formato fixo. O leitor reconhece cabeçalhos como
`nome`, `vendedor`, `loja`, `nickname`, `link`, `perfil`, `url`, `cidade`, `uf`, `seller_id`
em qualquer ordem, com `,` ou `;` como separador.

## Chaves (todas opcionais)

Sem nenhuma chave o pipeline já funciona: Mercado Livre, Receita Federal, DuckDuckGo e
raspagem de site não exigem cadastro. As chaves elevam a taxa de acerto:

| Variável | Para quê | Custo |
|---|---|---|
| `GOOGLE_MAPS_KEY` | telefone do Google Business — **a melhor fonte de telefone local** | ~US$ 0,035 por lead |
| `SERPAPI_KEY` ou `GOOGLE_CSE_KEY`+`GOOGLE_CSE_CX` | busca mais confiável que o DuckDuckGo, que limita volume | free tier costuma bastar |
| `CNPJWS_TOKEN` | limite maior de consultas de CNPJ | free tier |

Para 100 leads o custo de API fica na casa de poucos dólares.

## Base local da Receita (opcional, recomendado para escala)

Resolver "nome do vendedor → CNPJ" por buscador é o elo mais frágil da corrente.
Como todos os leads são de uma cidade só, dá para baixar os dados abertos do CNPJ e
manter **todas as empresas de Tubarão** num SQLite local:

```bash
python scripts/build_receita_local.py --municipio Tubarao --uf SC
```

Roda uma vez (download pesado, alguns GB). Depois disso a resolução por nome fica
offline, instantânea e muito mais precisa — e passa a achar empresa cujo nome no
Mercado Livre não tem nenhuma relação com a razão social.

## Reexecução é barata

Toda resposta HTTP vai para um cache SQLite em `.cache/`. Rodar de novo não repete
chamadas de rede, então dá para iterar no código sem recomeçar a coleta do zero.
Para forçar coleta nova, apague `.cache/`.

## Testes

```bash
python -m pytest tests -q
```

Cobrem validação de CNPJ, normalização de telefone brasileiro (celular × fixo, DDD,
descarte de CEP e CNPJ que parecem telefone), limpeza de e-mail, extração de dono de
MEI, leitura de planilha, pontuação e escrita da saída.

## Limites e cuidados

- **Rate limit**: 1 requisição por segundo por domínio, com retry exponencial. Não aumente
  sem necessidade — derrubar o acesso atrasa mais do que a espera.
- **Telefone da Receita pode estar velho.** Por isso o Google Maps e o site entram como
  fontes independentes; quando duas fontes concordam, a confiança sobe.
- **WhatsApp é inferido**, não confirmado: todo celular brasileiro é tratado como candidato.
  Confirmação de fato só com a API oficial do WhatsApp Business.
- **LGPD**: prospecção B2B se apoia em legítimo interesse (art. 7º, IX). Na prática isso pede
  identificar-se na abordagem, dizer como chegou até o contato e respeitar pedido de descarte.
  Os dados usados aqui são públicos (Receita Federal, site da empresa, perfil comercial),
  mas nome de sócio é dado pessoal — trate como tal.
