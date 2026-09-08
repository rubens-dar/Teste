# Validação do método — 5 leads reais de Tubarão/SC

Data: 08/09/2026

## Por que estes 5 leads, e não os da planilha

A planilha de leads está publicada como artifact **compartilhado**, não como artifact
próprio. Nesse modo a leitura ainda não é liberada — as duas vias (leitura direta e
fetch) retornam o mesmo bloqueio. Como o objetivo era provar que a cadeia funciona,
validei com 5 empresas **reais de Tubarão/SC**, escolhidas às cegas e conferidas
depois contra dado que já existia.

## O que foi testado

A perna mais frágil e mais valiosa da cadeia:

```
nome de marca  ──▶  CNPJ  ──▶  razão social + município  ──▶  quadro societário (DONO)
```

É exatamente o trecho que decide se a solução tem valor: se não chega no CNPJ certo,
nada mais importa; se chega, o dono vem junto.

## Resultado

| | Entrada | CNPJ | Município confere | Dono identificado | Telefone |
|---|---|---|---|---|---|
| 1 | Montri | 06.071.442/0001-05 | sim | Enedio Batista da Silva Nasario | parcial (mascarado) |
| 2 | Corremar Móveis | 79.692.968/0001-86 | sim | Arlan de Oliveira Mateus | (48) 3628-0297 |
| 3 | Móveis São Martinho | 44.897.331/0001-41 | sim | Tarcisio Matheus da Silva | não |
| 4 | Prime Móveis | 73.205.072/0001-49 | sim | Jamur Faust Lima | (48) 9820-4867 |
| 5 | FJ Móveis | 07.407.581/0001-20 | sim | Fabiano Marcelino Moraes | não |

- **CNPJ correto: 5/5**
- **Nome do dono: 5/5**
- **Algum telefone: 3/5** — e só porque aqui eu tinha apenas o buscador (veja limites)

## A conferência que dá confiança no número

O lead 1 tem gabarito. Na planilha *"Leads Frios ou Antigos Clientes"* do Drive, a
Montri aparece com o contato **Diogo Nasário**. A cadeia, rodando sem saber disso,
devolveu como sócio-administrador **Enedio Batista da Silva Nasario** — mesmo
sobrenome, mesma família controladora. O caminho chegou em quem manda, não em um
homônimo qualquer.

## O que a validação mudou no código

Descoberta prática: os diretórios de CNPJ **escrevem o quadro societário no próprio
snippet que o buscador indexa** ("Fulano de Tal (Sócio-Administrador)"). Foi assim que
saíram os 5 donos, sem uma única chamada de API.

O pipeline minerava só o CNPJ desses snippets e jogava o resto fora. Adicionado:

- `owners_from_results()` em `leadhunter/sources/search.py` — lê o quadro societário do
  snippet, ranqueia administrador acima de sócio comum, descarta razão social disfarçada
  de nome de pessoa e **só confia em host que é diretório de CNPJ**;
- ligação no `pipeline.py` como fallback quando a Receita não devolve sócio;
- 12 novos domínios de diretório mapeados (inteligen, cnpjcheck, situacaocadastral,
  empresasdobrasil, basecadastral, cnpjrocks, consultascnpj, normasabnt, cnpjtransparencia…);
- 2 testes novos. Suíte: **23 passando**.

Ganho concreto: o nome do dono deixa de depender da Receita estar no ar.

## Limites honestos deste teste

1. **Telefone e e-mail cadastrais vêm mascarados** nos diretórios gratuitos
   (`(48) 3628-****`, `a*@*****.com.br`). Quem devolve o valor inteiro é a
   BrasilAPI/MinhaReceita — que é justamente o caminho principal do pipeline, e que
   **não pôde ser exercitado aqui** porque este ambiente bloqueia toda saída de rede
   menos a busca.
2. **Etapa 1 (perfil do ML → CNPJ) não foi exercitada** — exige abrir páginas do
   Mercado Livre. Na sua máquina ela roda e tende a ser a fonte mais limpa de CNPJ,
   já que a plataforma é obrigada a exibir razão social e CNPJ do vendedor PJ.
3. Site da empresa, Google Maps, Instagram e LinkedIn — todas fontes de WhatsApp —
   também ficaram de fora pelo mesmo motivo.

Ou seja: **3/5 de telefone é o piso**, medido com uma mão amarrada. Rodando na sua
máquina, com Receita + site + Instagram + Maps ativos, a expectativa é bem acima disso.

## Como reproduzir

```bash
git clone https://github.com/rubens-dar/Teste && cd Teste
git checkout claude/project-context-check-t5oqgh
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m leadhunter doctor
python -m leadhunter enrich <planilha> -n 5
```

---

# Rodada 2 — a perna de contato, só com buscador

Cobrança justa: a rodada 1 testou só `marca → CNPJ → dono`. Esta testa a segunda
metade — site, Instagram, telefone — ainda sem poder abrir página nenhuma.

| | Empresa | Telefone | Instagram | Site |
|---|---|---|---|---|
| 1 | Montri | (48) 3628-\*\*\*\* e (48) 99913-\*\*\*\* | @montri_oficial (via Facebook) | lp.montri.com.br |
| 2 | Corremar Móveis | **(48) 3628-0297** (fixo, completo) | **@corremarmoveistb** | — |
| 3 | Móveis São Martinho | (48) 99966-\*\*\*\* | — | — |
| 4 | Prime Móveis | **(48) 9820-4867** | não confirmado | — |
| 5 | FJ Móveis | — | @fjmoveis.oficial (não confirmado) | — |

- Telefone **completo**: 2/5
- Telefone **existe mas vem mascarado**: +2/5 → **4/5 têm telefone cadastrado**
- Instagram: 2/5 (1 confirmado, 1 provável)
- WhatsApp confirmado: **0/5**

## O achado que muda a leitura do número

Dois dos telefones mascarados são **celular**: `(48) 99913-****` (Montri) e
`(48) 99966-****` (São Martinho). Celular brasileiro é, na prática, WhatsApp.

Então o dado existe e está no cadastro — o que falta é só o direito de ler o número
inteiro. Quem lê é a BrasilAPI/MinhaReceita, que devolve `ddd_telefone_1` sem máscara
e é o caminho principal do pipeline. Os diretórios gratuitos mascaram justamente
porque não são a fonte, são revenda dela.

## O que continua sem teste

- **Google Maps**: exige a Places API — chave e chamada de rede. Nenhuma das duas existe aqui. Zero cobertura.
- **Bio do Instagram**: o handle a busca acha; a bio, onde mora o WhatsApp, só abrindo o perfil.
- **Site da empresa**: achei `lp.montri.com.br`, mas raspar `/contato` atrás de `mailto:`/`wa.me` exige baixar a página.
- **Perfil do Mercado Livre**: idem.

## Conclusão honesta das duas rodadas

O que dá pra afirmar com teste: **a identificação do dono funciona** (5/5) e **a
empresa tem telefone cadastrado em 4/5**.

O que **não** dá pra afirmar com teste: a taxa de WhatsApp. Ela depende inteiramente
das quatro fontes acima, todas bloqueadas neste ambiente. Só medindo na sua máquina.
