"""
Funções auxiliares para gerenciar chaveamento de campeonatos
"""

import random


def gerar_chaveamento_quartas(equipes):
    """
    Gera o chaveamento para as quartas de final.
    Recebe uma lista de equipes e retorna uma lista de partidas (duplas de equipes).
    """
    # Embaralhar equipes para criar pareamentos aleatórios
    equipes_embaralhadas = equipes.copy()
    random.shuffle(equipes_embaralhadas)
    
    partidas = []
    for i in range(0, len(equipes_embaralhadas), 2):
        if i + 1 < len(equipes_embaralhadas):
            partidas.append({
                'equipe1': equipes_embaralhadas[i],
                'equipe2': equipes_embaralhadas[i + 1],
                'fase': 'quartas',
                'numero': len(partidas) + 1
            })
        else:
            # Se houver número ímpar, a última equipe passa direto
            partidas.append({
                'equipe1': equipes_embaralhadas[i],
                'equipe2': None,  # Sem oponente, passa direto
                'fase': 'quartas',
                'numero': len(partidas) + 1
            })
    
    return partidas


def calcular_saldo_gols(partida):
    """Calcula o saldo de gols de uma partida (gols do time 1 - gols do time 2)"""
    if partida['placar_equipe1'] is None or partida['placar_equipe2'] is None:
        return 0
    return partida['placar_equipe1'] - partida['placar_equipe2']


def obter_melhor_perdedor(db, campeonato_id, fase_atual):
    """
    Obtém o melhor perdedor (baseado no saldo de gols) da fase atual.
    Retorna o ID da equipe perdedora com melhor saldo de gols.
    """
    # Obter todas as partidas concluídas da fase atual
    partidas = db.execute(
        """SELECT pc.*, e1.nome as equipe1_nome, e2.nome as equipe2_nome
           FROM partidas_campeonato pc
           LEFT JOIN equipes e1 ON pc.equipe1_id = e1.id
           LEFT JOIN equipes e2 ON pc.equipe2_id = e2.id
           WHERE pc.campeonato_id = ? AND pc.fase = ? AND pc.status = 'concluído'
           ORDER BY pc.numero_partida""",
        (campeonato_id, fase_atual)
    ).fetchall()
    
    perdedores = []
    for partida in partidas:
        # Determinar o perdedor
        if partida['placar_equipe1'] is not None and partida['placar_equipe2'] is not None:
            if partida['placar_equipe1'] > partida['placar_equipe2']:
                perdedor_id = partida['equipe2_id']
                saldo = partida['placar_equipe2'] - partida['placar_equipe1']
            else:
                perdedor_id = partida['equipe1_id']
                saldo = partida['placar_equipe1'] - partida['placar_equipe2']
            
            perdedores.append({
                'equipe_id': perdedor_id,
                'saldo_gols': saldo
            })
    
    # Ordenar por saldo de gols (maior primeiro) e retornar o melhor
    if perdedores:
        perdedores.sort(key=lambda x: x['saldo_gols'], reverse=True)
        return perdedores[0]['equipe_id']
    
    return None


def gerar_chaveamento_semis(vencedores, melhor_perdedor=None):
    """
    Gera o chaveamento para as semifinais a partir dos vencedores das quartas.
    Se houver número ímpar de vencedores, o melhor_perdedor completa a chave.
    """
    vencedores_lista = list(vencedores) if not isinstance(vencedores, list) else vencedores
    
    # Se houver número ímpar, adicionar o melhor perdedor
    if len(vencedores_lista) % 2 != 0 and melhor_perdedor:
        vencedores_lista.append(melhor_perdedor)
    
    # Se ainda houver número ímpar (sem melhor perdedor), escolher um time aleatório para passar direto
    if len(vencedores_lista) % 2 != 0:
        # Um time passa direto
        time_bye = random.choice(vencedores_lista)
        vencedores_lista.remove(time_bye)
        partidas = []
        for i in range(0, len(vencedores_lista), 2):
            if i + 1 < len(vencedores_lista):
                partidas.append({
                    'equipe1': vencedores_lista[i],
                    'equipe2': vencedores_lista[i + 1],
                    'fase': 'semi',
                    'numero': len(partidas) + 1
                })
        # Adicionar o time que passa direto como uma "partida" sem oponente
        partidas.append({
            'equipe1': time_bye,
            'equipe2': None,
            'fase': 'semi',
            'numero': len(partidas) + 1
        })
        return partidas
    
    # Embaralhar para criar pareamentos aleatórios
    vencedores_embaralhados = vencedores_lista.copy()
    random.shuffle(vencedores_embaralhados)
    
    partidas = []
    for i in range(0, len(vencedores_embaralhados), 2):
        if i + 1 < len(vencedores_embaralhados):
            partidas.append({
                'equipe1': vencedores_embaralhados[i],
                'equipe2': vencedores_embaralhados[i + 1],
                'fase': 'semi',
                'numero': len(partidas) + 1
            })
    
    return partidas


def gerar_chaveamento_final(vencedores, melhor_perdedor=None):
    """
    Gera a final a partir dos vencedores das semifinais.
    Se houver apenas 1 vencedor, o melhor_perdedor completa a final.
    """
    vencedores_lista = list(vencedores) if not isinstance(vencedores, list) else vencedores
    
    # Se houver apenas 1 vencedor, adicionar o melhor perdedor
    if len(vencedores_lista) == 1 and melhor_perdedor:
        vencedores_lista.append(melhor_perdedor)
    
    if len(vencedores_lista) >= 2:
        return [{
            'equipe1': vencedores_lista[0],
            'equipe2': vencedores_lista[1],
            'fase': 'final',
            'numero': 1
        }]
    
    return []


def gerar_chaveamento_terceiro_lugar(perdedores_semis):
    """
    Gera a partida de terceiro lugar a partir dos perdedores das semifinais.
    """
    if len(perdedores_semis) >= 2:
        return [{
            'equipe1': perdedores_semis[0],
            'equipe2': perdedores_semis[1],
            'fase': 'terceiro_lugar',
            'numero': 1
        }]
    return []


def obter_times_que_passam_direto(db, campeonato_id, fase):
    """
    Obtém os times que passaram direto (sem oponente) em uma fase.
    """
    times_bye = db.execute(
        """SELECT equipe1_id FROM partidas_campeonato 
           WHERE campeonato_id = ? AND fase = ? AND equipe2_id IS NULL""",
        (campeonato_id, fase)
    ).fetchall()
    
    return [t['equipe1_id'] for t in times_bye]
