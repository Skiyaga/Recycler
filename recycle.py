import argparse, os
from recycle.utils import *


def parse_user_input():
    parser = argparse.ArgumentParser(
        description=
        'recycle extracts cycles likely to be plasmids from metagenome and genome assembly graphs'
        )
    parser.add_argument('-g','--graph',
     help='(spades 3.50+) FASTG file to process [recommended: before_rr.fastg]',
     required=True, type=str
     )
    parser.add_argument('-l', '--length',
     help='minimum length required for reporting [default: 1000]',
     required=False, type=int, default=1000
     )
    parser.add_argument('-m', '--max_CV',
     help='coefficient of variation used for pre-selection '+
     '[default: 0.25, higher--> less restrictive]; Note: not a requisite for selection',
      required=False, default=1./4, type=float
      )
    parser.add_argument('-b','--bam', 
        help='BAM file resulting from aligning reads to contigs file, filtering for best matches', 
        required=True, type=str
        )
    
    return parser.parse_args()



####### entry point  ##############
# inputs: spades assembly fastg, BAM of reads aligned to unitigs
# outputs: fasta of cycles found by joining component edges

###################################
# read in fastg, load graph, create output handle
args = parse_user_input()
fastg = args.graph
max_CV = args.max_CV
min_length = args.length
fp = open(fastg, 'r')
files_dir = os.path.dirname(fp.name)

# output 1 - fasta of sequences
(root,ext) = os.path.splitext(fp.name)
fasta_ofile = root + ext.replace(".fastg", ".cycs.fasta")
f_cycs_fasta = open(fasta_ofile, 'w')
# output 2 - file containing path name (corr. to fasta), 
# path, coverage levels when path is added
cycs_ofile = root + ext.replace(".fastg", ".cycs.paths_w_cov.txt")
f_cyc_paths = open(cycs_ofile, 'w')
bamfile = pysam.AlignmentFile(args.bam)


###################################
# graph processing begins


G = get_fastg_digraph(fastg)
path_count = 0
# gets set of long simple loops, removes short
# simple loops from graph
SEQS = get_fastg_seqs_dict(fastg,G)
long_self_loops = get_long_self_loops(G, min_length, SEQS)
non_self_loops = set([])
VISITED_NODES = set([]) # used to avoid problems due to RC nodes we may have removed
final_paths_dict = {}

for nd in long_self_loops:
    name = get_spades_type_name(path_count, nd, 
        SEQS, G, get_cov_from_spades_name(nd[0]))
    final_paths_dict[name] = nd
    path_count += 1

comps = nx.strongly_connected_component_subgraphs(G)
COMP = nx.DiGraph()
redundant = False
print "================== path, coverage levels when added ===================="

###################################
# iterate through SCCs looking for cycles
for c in comps:
    # check if any nodes in comp in visited nodes
    # if so continue
    for node in c.nodes():
        if c in VISITED_NODES:
            redundant = True
            break
    if redundant:
        redundant = False
        continue # have seen the RC version of component
    COMP = c.copy()
    # SEQS = get_fastg_seqs_dict(fastg, COMP)

    # initialize shortest path set considered
    paths = enum_high_mass_shortest_paths(COMP)
    
    # peeling - iterate until no change in path set from 
    # one iteration to next
 
    last_path_count = 0
    last_node_count = 0
    # continue as long as you either removed a low mass path
    # from the component or added a new path to final paths
    while(path_count!=last_path_count or\
        len(COMP.nodes())!=last_node_count):

        last_node_count = len(COMP.nodes())
        last_path_count = path_count

        if(len(paths)==0): break

        # using initial set of paths or set from last iteration
        # sort the paths by CV and test the lowest CV path for removal 
        # need to use lambda because get_cov needs 2 parameters
        
        # make tuples of (CV, path)
        path_tuples = []
        for p in paths:
            path_tuples.append((get_wgtd_path_coverage_CV(p,COMP,SEQS), p))
        
        # sort in ascending CV order
        path_tuples.sort(key=lambda path: path[0]) 
        
        curr_path = path_tuples[0][1]
        if get_total_path_mass(curr_path,COMP)<1:
            for n in curr_path:
                update_node_coverage(COMP,n,0)
            # recalc. paths since some might have been disrupted
            non_self_loops.add(get_unoriented_sorted_str(curr_path))
            paths = enum_high_mass_shortest_paths(COMP,non_self_loops)
            continue

        if get_wgtd_path_coverage_CV(curr_path,COMP,SEQS) <= max_CV and \
        get_unoriented_sorted_str(curr_path) not in non_self_loops:

            covs_before_update = [get_cov_from_spades_name_and_graph(p,COMP) for p in curr_path]
            cov_val_before_update = get_total_path_mass(curr_path,COMP) /\
             len(get_seq_from_path(curr_path, SEQS))
            path_nums = [get_num_from_spades_name(p) for p in curr_path]
            update_path_coverage_vals(curr_path, COMP, SEQS)
            name = get_spades_type_name(path_count,curr_path, SEQS, COMP, cov_val_before_update)
            path_count += 1
            non_self_loops.add(get_unoriented_sorted_str(curr_path))

            # only report to file if long enough and good
            if len(get_seq_from_path(curr_path, SEQS))>=min_length and is_good_cyc(curr_path,G,bamfile):
                print curr_path
                print "before", covs_before_update
                print "after", [get_cov_from_spades_name_and_graph(p,COMP) for p in curr_path]
                final_paths_dict[name] = curr_path

                f_cyc_paths.write(name + "\n" +str(curr_path)+ "\n" + str(covs_before_update) 
                    + "\n" + str(path_nums) + "\n")
            # recalculate paths on the component
            print len(COMP.nodes()), " nodes remain in component\n"
            
            paths = enum_high_mass_shortest_paths(COMP,non_self_loops)
    rc_nodes = [rc_node(n) for n in COMP.nodes()]
    VISITED_NODES.update(COMP.nodes())
    VISITED_NODES.update(rc_nodes)

# done peeling
# print final paths to screen
print "==================final_paths identities after updates: ================"

# write out sequences to fasta
for p in final_paths_dict.keys():
    seq = get_seq_from_path(final_paths_dict[p], SEQS)
    print final_paths_dict[p]
    print ""
    if len(seq)>=min_length:
        f_cycs_fasta.write(">" + p + "\n" + seq + "\n")    

