#!/usr/bin/env python3
"""Deterministic first-frame positions for fixed country/community overviews.

These are display coordinates, not graph facts. ForceGraph may refine them
after first paint; selected institutions and focused graphs still lay out live.
"""
import hashlib
import math
from collections import defaultdict

GOLDEN_ANGLE = 2.399963229728653


def stable_angle(value):
    number = int.from_bytes(hashlib.blake2b(value.encode(), digest_size=8).digest(), 'big')
    return number / (2 ** 64) * 2 * math.pi


def layout_for(nodes, lens):
    groups = defaultdict(list)
    for node in nodes:
        membership = node.get('communities', {}).get('coauthor' if lens == 'none' else lens, {})
        group = membership.get('id', 'unconnected')
        if lens == 'none' and group == 'unconnected':
            group = 'solo:' + node['id']
        groups[group].append(node)
    ranked = sorted(groups, key=lambda key: (-len(groups[key]), key))
    coordinates = {}
    for index, key in enumerate(ranked):
        members = sorted(groups[key], key=lambda item: item['id'])
        centre_radius = 0 if index == 0 else (230 + 150 * math.sqrt(min(index, 200)) +
                                               40 * math.sqrt(max(0, index - 200)))
        centre_angle = index * GOLDEN_ANGLE
        cx, cy = centre_radius * math.cos(centre_angle), centre_radius * math.sin(centre_angle)
        for position, node in enumerate(members):
            # Packed local spiral: stable across snapshot rebuilds and cheap to
            # paint, with a later live simulation available for fine adjustment.
            radius = 13 * math.sqrt(position + 0.5)
            angle = position * GOLDEN_ANGLE + stable_angle(key)
            coordinates[node['id']] = [round(cx + radius * math.cos(angle), 1),
                                       round(cy + radius * math.sin(angle), 1)]
    return coordinates


def add_layouts(graph):
    nodes = graph['nodes']
    for lens in ('none', 'coauthor', 'topic', 'institution'):
        positions = layout_for(nodes, lens)
        for node in nodes:
            node.setdefault('layouts', {})[lens] = positions[node['id']]
    return graph
