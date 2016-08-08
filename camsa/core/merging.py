# -*- coding: utf-8 -*-
# noinspection PyCompatibility
import enum
from collections import defaultdict

import blist
import networkx

from core.data_structures import MergedAssemblyGraph, inverse_orientation


class MergingStrategies(enum.Enum):
    progressive_merging = "progressive-merging"
    maximal_matching = "maximal-matching"


def get_scaffold_edges(assembly_points):
    unique_scaffolds = set()
    for ap in assembly_points:
        unique_scaffolds.add(ap.seq1)
        unique_scaffolds.add(ap.seq2)
    return [(name + "t", name + "h") for name in unique_scaffolds]


def get_un_oriented_assembly_points(assembly_points):
    return {ap for ap in assembly_points if ap.is_unoriented}


####################################################################
####################################################################
#                                                                  #
# Progressive merging strategy for combining scaffold assemblies   #
#                                                                  #
####################################################################

def merge_progressively(assembly_points_by_sources, acyclic=True, min_cw=0.0):
    def get_redundant_edges_from_assembly_points(e, points_by_edges, processed_points):
        result = []
        for assembly_point in points_by_edges[e]:
            if assembly_point in processed_points:
                continue
            processed_points.add(assembly_point)
            for ap_representation_edge in assembly_point.get_edges(sort=True):
                result.append(ap_representation_edge)
        return result

    assembly_points_by_sources = [ap for ap_list in assembly_points_by_sources.values() for ap in ap_list]
    already_processed_assembly_points = set()
    scaffold_edges = get_scaffold_edges(assembly_points=assembly_points_by_sources)
    cover_graph = networkx.Graph()
    cover_graph.add_edges_from(scaffold_edges)
    end_points = {}
    for (u, v) in cover_graph.edges_iter():
        end_points[u] = v
        end_points[v] = u

    assembly_edges_graph = MergedAssemblyGraph()
    assembly_points_by_edges = defaultdict(list)
    for ap in assembly_points_by_sources:
        for (u, v, weight) in ap.get_edges(sorted=True, weight=True):
            assembly_points_by_edges[(u, v)].append(ap)
            assembly_edges_graph.add_edge(u, v, weight=weight)
    assembly_edges_graph.remove_edges_with_low_cw(cw_threshold=min_cw)
    assembly_edges = assembly_edges_graph.edges(weight=True)
    sorted_assembly_edges = sorted(assembly_edges, key=lambda entry: entry[2])
    assembly_edges = blist.sortedlist(sorted_assembly_edges, key=lambda entry: entry[2])

    while len(assembly_edges) > 0:
        edge = assembly_edges.pop()
        redundant_edges = set()
        u, v, w = edge
        if (end_points[u] == v or end_points[v] == u) and acyclic:  # endpoints of the same path and graph is restrained to be acyclic
            redundant_edges.add((u, v))
        else:
            # growing the cover
            cover_graph.add_edge(u, v, weight=w)
            # updating endpoints of merged paths
            end_points[end_points[u]], end_points[end_points[v]] = end_points[v], end_points[u]
            # collecting redundant edges
            re1 = {tuple(sorted(e)) for e in assembly_edges_graph.graph.edges(nbunch=u)}
            re2 = {tuple(sorted(e)) for e in assembly_edges_graph.graph.edges(nbunch=v)}
            re3 = {tuple(sorted(e)) for e in get_redundant_edges_from_assembly_points(e=(u, v), points_by_edges=assembly_points_by_edges,
                                                                                      processed_points=already_processed_assembly_points)}
            redundant_edges.add(tuple(sorted((u, v))))
            redundant_edges.update(re1)
            redundant_edges.update(re2)
            redundant_edges.update(re3)
        for u, v in redundant_edges:
            to_discard = (u, v, assembly_edges_graph.graph[u][v]['weight'])
            assembly_edges.discard(to_discard)
    # checking that we didn't screw up :)
    for vertex in cover_graph.nodes():
        if cover_graph.degree(vertex) > 2:
            print(vertex)
            print(cover_graph.edges(nbunch=vertex))
            exit(1)
    return cover_graph


####################################################################
####################################################################
#                                                                  #
# Maximal matching strategy for combining scaffold assemblies      #
#                                                                  #
####################################################################

def maximal_matching(assembly_points_by_sources, acyclic=True, min_cw=0.0):
    assembly_points_by_sources = [ap for ap_list in assembly_points_by_sources.values() for ap in ap_list]
    scaffold_edges = get_scaffold_edges(assembly_points=assembly_points_by_sources)
    unoriented_assembly_points = get_un_oriented_assembly_points(assembly_points=assembly_points_by_sources)

    assembly_edges_graph = MergedAssemblyGraph()
    for ap in assembly_points_by_sources:
        for (u, v, weight) in ap.get_edges(sort=True, weight=True):
            assembly_edges_graph.add_edge(u, v, weight=weight)
    assembly_edges_graph.remove_edges_with_low_cw(cw_threshold=min_cw)
    matching = networkx.max_weight_matching(G=assembly_edges_graph.graph)
    cover_graph = networkx.Graph()
    cover_graph.add_edges_from(scaffold_edges)
    edges = get_edges_from_matching(matching)
    for u, v in edges:
        cover_graph.add_edge(u, v, weight=assembly_edges_graph.graph[u][v]['weight'])
    # sanity check
    for vertex in cover_graph.nodes():
        assert cover_graph.degree(vertex) <= 2
    # checking for any issues with unoriented assembly points
    for assembly_point in unoriented_assembly_points:
        participating_edges = []
        for (u, v) in assembly_point.get_edges():
            if cover_graph.has_edge(u=u, v=v):
                participating_edges.append((u, v))
        assert len(participating_edges) <= 2  # this is just a sanity check
        if len(participating_edges) == 2:
            cover_graph.remove_edge(participating_edges[0][0], participating_edges[0][1])
    edges_to_delete = []
    for cc in networkx.connected_component_subgraphs(G=cover_graph, copy=False):
        if networkx.number_of_nodes(cc) == networkx.number_of_edges(cc):
            edges_to_delete.append(min(cc.edges(data=True), key=lambda edge: edge))
    return cover_graph


def get_edges_from_matching(matching):
    seen = set()
    edges = []
    for key, value in matching.items():
        if key not in seen and value not in seen:
            edges.append((key, value))
            seen.add(key)
            seen.add(value)
    return edges


strategies_bindings = {
    MergingStrategies.progressive_merging.value: merge_progressively,
    MergingStrategies.maximal_matching.value: maximal_matching
}


def update_assembly_points_with_merged_assembly(original_assembly_points_by_ids, merged_assembly_points_by_ids, merged_assembly_graph):
    for ap in merged_assembly_points_by_ids.values():
        for u, v in ap.get_edges():
            if merged_assembly_graph.has_edge(u=u, v=v):
                par_or_1 = "+" if u.endswith("h") else "-"
                par_or_2 = "+" if v.endswith("t") else "-"
                forward = u[:-1] == ap.seq1
                if not forward:
                    par_or_1, par_or_2 = inverse_orientation(par_or_2), inverse_orientation(par_or_1)
                ap.seq1_par_or = par_or_1
                ap.seq2_par_or = par_or_2
                ap.participates_in_merged = True
                for child_id in ap.children_ids:
                    child = original_assembly_points_by_ids[child_id]
                    child.participates_in_merged = True
                    child.seq1_par_or = par_or_1
                    child.seq2_par_or = par_or_2
                break