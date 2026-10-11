# pii-mask

Tira o dado pessoal do prompt antes de ele sair da sua rede — e põe de volta na resposta.

```python
from pii_mask import mask

masked, vault = mask("Cliente Maria, CPF 529.982.247-25, tel (11) 98765-4321")
# 'Cliente Maria, CPF PII475CB7D0, tel PII30A573BB'

resposta = chame_o_modelo(masked)
final = vault.unmask(resposta)
```

CPF, CNPJ, cartão, telefone e e-mail — cada um **confirmado pelo dígito verificador**, não por regex. Zero dependências. Nada vai para lugar nenhum: isso roda antes.

---

## Por que não é só um regex

```python
re.compile(r"\d{11}")
```

Esse é o primeiro código que todo mundo escreve, e ele erra nos dois sentidos ao mesmo tempo.

Rodando num atendimento de verdade, ele casou três coisas:

```
52998224726  ->  NÃO é CPF   (número de pedido)
11987654321  ->  NÃO é CPF   (celular com DDD)
52998224725  ->  é CPF
```

**Um celular brasileiro com DDD tem exatamente onze dígitos.** Então o regex reporta todo telefone do documento como CPF — e mascará-los como CPF é pior do que não mascarar, porque agora o log diz que você tratou um dado que não tratou.

E ele **não enxerga** `529.982.247-25`. Essa string não tem nenhuma sequência de onze dígitos.

A forma é encontrada de maneira frouxa e depois **verificada**: puxa os dígitos, recalcula o dígito verificador. Número que não fecha não é dado pessoal; número que fecha quase certamente é.

---

## Os cinco bugs que moldaram o código

### 1. `[CPF_1]` não sobrevive à viagem

O difícil não é mascarar. É que o texto **volta reescrito**: o modelo reordena, cita um trecho, traduz os rótulos ao redor.

`[CPF_1]` é prosa. Tem pontuação que o modelo reformata, uma palavra que ele pode traduzir e um número que ele pode renumerar. `[CPF 1]`, `[cpf_1]` e `(CPF_1)` voltam todos irrestauráveis — e a falha é **silenciosa**: a resposta simplesmente ainda tem um placeholder, o que parece defeito de formatação e não dado perdido.

O token aqui é uma palavra alfanumérica opaca, sem pontuação e sem nada para traduzir: `PII475CB7D0`.

### 2. O mesmo CPF escrito de dois jeitos virava duas pessoas

Esse apareceu rodando a demo. O documento tinha `529.982.247-25` numa linha e `52998224725` em outra — o mesmo CPF da mesma Maria — e cada um ganhou um token diferente.

Da perspectiva do modelo, são dois documentos de duas pessoas. E ele responde de acordo.

O token passou a ser derivado do valor **canônico**, não do texto: só os dígitos para CPF, CNPJ, cartão e telefone (descartando o `+55`), e `casefold` para e-mail. Hoje os dois viram um token só, e o modelo volta a ver uma pessoa.

O custo está documentado e tem teste: um valor escrito de duas formas **volta escrito da primeira forma**. É uma troca deliberada, e a alternativa é pior.

### 3. O ponto final da frase apagava todos os telefones

O padrão de telefone tinha guardas `(?<![\d.])` e `(?![\d.])` — excluindo ponto dos dois lados, para não casar dentro de um valor formatado tipo `R$ 1.234,56`.

Resultado: parou de reconhecer todo telefone **no fim de uma frase**, porque o ponto estava ali. Que é onde telefone costuma aparecer.

Os guardas hoje só barram dígito. Sobreposição é problema de `resolve()`, que é o lugar certo para resolver isso.

### 4. Candidatos se sobrepõem, e o segundo corrompe o primeiro

Um CNPJ tem quatorze dígitos, e dentro dele existem sequências de onze. O detector de CPF encontra uma delas, e agora os mesmos caracteres pertencem a dois achados — e qualquer substituição feita em segundo lugar corrompe o texto que a primeira produziu.

`resolve()` mantém o mais longo, com a ordem dos detectores desempatando. Então `12.345.678/0001-95` é um CNPJ, e não um CPF com sujeira em volta.

Pelo mesmo motivo, `unmask` é **uma passada** com um único regex, nunca um laço de `str.replace`: o laço reexamina texto que já restaurou, e dois tokens em que um é prefixo do outro dão resultado dependente da ordem do dicionário.

### 5. `111.111.111-11` fecha a conta

A aritmética aceita. É o placeholder mais antigo do software brasileiro, e tratar uma fixture como achado é ruído no melhor caso — e no pior, um arquivo de teste mascarado. Dígitos todos iguais são rejeitados explicitamente, tanto para CPF quanto para CNPJ.

Na mesma linha, três detalhes que parecem preciosismo e não são:

- **DDD é tabela, não intervalo.** 10 a 19 existem, mas 20, 23, 25, 26, 29, 36, 39, 40 e vários outros não. Aceitar dois dígitos quaisquer faz a primeira metade de um código de produto de onze dígitos virar telefone.
- **Luhn sozinho aceita quatro dígitos.** Sem checar comprimento, o detector de cartão um dia redige o total de uma nota fiscal.
- **CEP está fora do conjunto padrão.** Ele identifica uma rua, não uma pessoa, e mascará-lo costuma destruir exatamente o endereço que o modelo foi contratado para tratar. `mask(texto, detectors=[*DEFAULT, CEP])` se você quiser.

---

## API

```python
mask(text, *, detectors=DEFAULT, style=Style.TOKEN) -> (str, Vault)
scan(text, detectors=DEFAULT) -> list[Candidate]      # auditar sem mascarar

vault.unmask(reply)    # restaura onde o token sobreviveu
vault.missing(reply)   # tokens que NÃO voltaram
vault.leaked(text)     # valores originais que aparecem no texto, para assert
vault.kinds            # {'cpf': 2, 'phone': 1} para a linha de log
```

`vault.missing()` é a verificação que vale rodar antes de repassar a resposta do modelo. Token que o modelo derrubou ou reescreveu significa valor que não voltou, e **nada na resposta parece errado** — ela só diz menos do que deveria.

Três estilos:

| Estilo | Saída | Reversível |
| --- | --- | --- |
| `TOKEN` | `PII475CB7D0` | sim |
| `LABEL` | `[cpf]` | não |
| `PARTIAL` | `***.***.*47-25` | não |

`PARTIAL` trata e-mail de outro jeito, e tem que tratar: guardar os últimos quatro caracteres deixa `*****@*******.*om.br`, que não identifica ninguém e também não ajuda ninguém. Então mascara a parte local e mantém o domínio: `m****@empresa.com.br`.

E `PARTIAL` **não é anônimo**: valor parcial mais um nome costuma identificar a pessoa. Na dúvida, `LABEL`.

## Sobre o cofre

A chave é aleatória por cofre, então dois cofres dão tokens diferentes ao mesmo valor. É deliberado: token estável entre requisições permitiria a quem comparasse dois documentos mascarados descobrir que tratam da mesma pessoa — exatamente a inferência que mascarar existe para impedir.

Um cofre serve uma viagem. Não reuse entre requisições.

## Rodando

```bash
pip install -e ".[dev]"
pytest                      # 122 testes
python examples/demo.py     # o regex ingênuo, este, e a viagem completa
```

A demo não acessa rede nenhuma.

---

## English summary

**pii-mask** removes Brazilian personal data from a prompt before it leaves your network and restores it in the reply. CPF, CNPJ, card, phone and email, each confirmed by its check digits rather than by a regex alone — because `\d{11}` matches an order number and, since a Brazilian mobile with its area code is exactly eleven digits, every phone number in the document, while missing `529.982.247-25` entirely.

Five bugs shaped it. A placeholder like `[CPF_1]` does not survive the round trip: it is prose, and comes back reformatted and unrestorable, silently. The same CPF written two ways was getting two tokens, so the model saw two people — tokens are now derived from a canonical form, at the documented cost that a value written two ways comes back written the first way. The phone pattern excluded a dot on either side and therefore stopped recognising every phone number at the end of a sentence. Overlapping candidates had to be resolved, longest first, or the second substitution corrupts the first's output — and for the same reason `unmask` is one regex pass, never a `str.replace` loop. And `111.111.111-11` satisfies the arithmetic, so all-identical digits are rejected explicitly.

`vault.missing()` reports tokens the model dropped, which is the failure nothing else notices. The vault key is random per vault, so a token cannot be used to link two masked documents to the same person.

Zero dependencies, Python 3.10+, strict mypy, 122 tests, CI on Linux and Windows.

## Licença

MIT
