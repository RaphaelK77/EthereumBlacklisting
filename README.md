# EthereumBlacklisting

A software created for the Bachelor's Thesis "Design and Analysis of Approaches toward the Regulation of DEXs".
It was designed to analyse the five blacklisting policies proposed for Ethereum in the course of the thesis.
The analysis requires access to an Ethereum archive node, and provides a module for synchronizing and running a local Erigon node (available here: https://github.com/ledgerwatch/erigon).

The program can be configured using the config.ini and the main.py files.
The main file allows for the customization using different datasets (the 4 datasets used in the thesis are included), and different policies as well as block ranges.

The program is then executed as follows:

To run the analysis program:
> python main.py --policy <'Poison', 'Haircut', 'FIFO', 'Seniority', or 'Reversed_Seniority'> --dataset \<dataset number>

To run the Erigon node:
> python node_process_handler <start_block>

All blocks up to start_block will be pruned and not available to the analysis program.
