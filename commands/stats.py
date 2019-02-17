from __future__ import print_function

import argparse
import pyjq
import yaml

from collections import Counter

from shared.nodes import Account, Region
from shared.common import parse_arguments, query_aws, get_regions, log_debug, slurp_parameter_files

__description__ = "Print counts of resources for accounts"


def output_image(accounts, account_stats, resource_names, output_image_file):
    # Display graph
    import matplotlib
    matplotlib.use('Agg')
    import pandas as pd
    import seaborn as sns
    import matplotlib.pyplot as plt

    # Reverse order of accounts so they appear in the graph correctly
    accounts = list(reversed(accounts))

    account_names = ['Resource']
    for account in accounts:
        account_names.append(account['name'])

    data = []
    for resource_name in resource_names:
        resource_array = [resource_name]
        for account in accounts:
            count = sum(account_stats[account['name']][resource_name].values())
            resource_array.append(count)
        data.append(resource_array)

    df = pd.DataFrame(
        columns=account_names,
        data=data)

    sns.set()
    plot = df.set_index('Resource').T.plot(kind='barh', stacked=True, fontsize=10, figsize=[8,0.3*len(accounts)])
    plt.legend(loc='center left', bbox_to_anchor=(1.0, 0.5))
    fig = plot.get_figure()
    # TODO: Set color cycle as explained here https://stackoverflow.com/questions/8389636/creating-over-20-unique-legend-colors-using-matplotlib
    # This is needed because there are 17 resources graphed, but only 10 colors in the cycle.
    # So if you have only S3 buckets and CloudFront, you end up with two blue bands
    # next to each other.

    fig.savefig(output_image_file, format='png', bbox_inches='tight', dpi=200)
    print('Image saved to {}'.format(output_image_file), file=sys.stderr)


def count_tags(region, resource, tag, aws_data):
    if 'tags_query' in resource:
        query = resource['tags_query'].format(tag)
        if ".json" in resource['tags_source']:
            aws_data = query_aws(region.account, resource['tags_source'].replace(".json", ""), region)
        else:
            aws_data = slurp_parameter_files(region, resource['tags_source'])
    else:
        query = resource['query'].replace('|length', '[]|.Tags[]?|select(.Key == "{}")|.Value'.format(tag))

    tags = pyjq.all(query, aws_data)
    return Counter(tags)


def count_terraformed_resources(region, resource, aws_data):
    if "no_tags" in resource:
        return "--"
    counter = count_tags(region, resource, "Terraform", aws_data)
    return counter["1"] + counter["true"]


def get_account_stats(account):
    """Returns stats for an account"""

    with open("stats_config.yaml", 'r') as f:
        resources = yaml.safe_load(f)

    account = Account(None, account)
    log_debug('Collecting stats in account {} ({})'.format(account.name, account.local_id))

    stats = {}
    stats['keys'] = []
    for resource in resources:
        stats['keys'].append(resource['name'])
        stats[resource['name']] = {}

    for region_json in get_regions(account):
        region = Region(account, region_json)

        for resource in resources:
            # Skip global services (just CloudFront)
            if ('region' in resource) and (resource['region'] != region.name):
                continue

            # Normal path
            aws_data = query_aws(region.account, resource['source'], region)

            stats[resource['name']][region.name] = {
                "count": sum(pyjq.all(resource['query'], aws_data)),
                "Terraform": count_terraformed_resources(region, resource, aws_data)
            }

    return stats


def stats(accounts):
    '''Collect stats'''

    # Collect counts
    account_stats = {}
    for account in accounts:
        account_stats[account['name']] = get_account_stats(account)
        resource_names = account_stats[account['name']]['keys']

    # Print header
    print('account,resource,count,Terraform')

    for resource_name in resource_names:
        for account in accounts:
            resource_stats = account_stats[account['name']][resource_name].values()
            resource_counts = [stat["count"] for stat in resource_stats]
            resource_total = sum(resource_counts)

            tf_counts = [stat["Terraform"] for stat in resource_stats]
            if "--" in tf_counts:
                tf_total = "--"
            else:
                tf_total = sum(tf_counts)

            print("{},{},{},{}".format(account["name"], resource_name, resource_total, tf_total))


def run(arguments):
    parser = argparse.ArgumentParser()

    parser.add_argument('--output_image',
        help='Name of output image', default='resource_stats.png', type=str)
    parser.add_argument("--no_output_image", help="Don't create output image",
        default=False, action='store_true')

    args, accounts, config = parse_arguments(arguments, parser)

    stats(accounts)
