import requests
import json
import pandas as pd
import numpy as np

class getJob:
    def __init__(self, jobID, jobType):
        super().__init__()
        """
        jobID: This is the task number of your GNPS job which can be found in the url of your GNPS job
        jobType: The type of job options are 'canopus', 'library', 'analog', 'csiFingerID', 'edges'
        
        canopus, library and edges are all files which are needed to run the EcoNet pipeline
        """

        # Requesting tsv output from GNPS API
        self.id = jobID

        if jobType == 'canopus':
            url = str('https://gnps.ucsd.edu/ProteoSAFe/result_json.jsp?task=' + self.id + '&view=canopus_summary') 
        if jobType == 'library':
            url = str('https://gnps.ucsd.edu/ProteoSAFe/result_json.jsp?task=' + self.id + '&view=view_all_annotations_DB')
        if jobType == 'analog':
            url = str('https://gnps.ucsd.edu/ProteoSAFe/result_json.jsp?task=' + self.id + '&view=view_all_analog_annotations_DB')
        # if jobType == 'network': #Fix this one
        #     url = str('https://gnps.ucsd.edu/ProteoSAFe/result_json.jsp?task=' + self.id + '&view=clusterinfo_summary')
        if jobType == 'csiFingerID':
            url = str('https://gnps.ucsd.edu/ProteoSAFe/result_json.jsp?task=' + self.id + '&view=compound_identifications_summary')
        if jobType == 'edges':
            url = str('https://gnps.ucsd.edu/ProteoSAFe/result_json.jsp?task=' + self.id + '&view=network_pairs_specnets_allcomponents')
        # if jobType == 'network':
            # url = str('https://gnps.ucsd.edu/ProteoSAFe/result_json.jsp?task=' + self.id + 'view=download_cytoscape_data')

        # request JSON files from GNPS, clean and load into pandas
        self.request = requests.get(url) # Download JSON from GNPS
        self.clean = self.request.text.replace('{ "blockData" : [', '[').replace('] }', ']').strip()
        self.df = pd.read_json(self.clean)

class mergeAnnotations:
    def __init__(self, canopus, network, analog = None):
        """
        library: The library match file downloaded from GNPS
        canopus: The Canopus file which can be downloaded from the SIRIUS workflow
        network: The Network file which is found in the clusterInfoSummary directory downloaded from GNPS
        analog: (Optional) The Analog file which can be downloaded from GNPS.

        All inputs need to be pd.DataFrames and not modified from how GNPS exports them.
        The dataframes can be directly downloaded using getJob() with the correct jobType specified.

        This function will return self.library and self.insilico which will have the library and insilico merged files for use in weighting and annotation propogation.
        """
        super().__init__()

        #Joining supplied dataframes
        if isinstance(analog, pd.DataFrame):
            self.matches = network.merge(analog, on = 'scan', how = 'outer')
            self.matches = self.matches.merge(canopus, on = 'scan', how = 'outer')   
            self.grouped = self.matches.groupby('network').apply(lambda x: x.dropna(subset = ['superclass_analog', 'superclass_canopus'], how = 'all'))

        if not isinstance(analog, pd.DataFrame):
            self.matches = network.merge(canopus, on = 'scan', how = 'outer')
            self.grouped = self.matches.groupby('network').apply(lambda x: x.dropna(subset = ['superclass_canopus']))

        # Make a list of networks which have at least one Library Match and remove them from the analog/canopus annotaitons
        
        self.insilico = self.grouped

class weightEdges:
    def __init__(self, edges):
        sumCosine = []

        for num in [1, 2]:
            cluster = str('CLUSTERID' + str(num))
            clusterSum = edges.df[[cluster, 'ComponentIndex', 'Cosine']].groupby(['ComponentIndex', cluster]).sum().reset_index().rename(columns = {cluster: 'scan'})
            sumCosine.append(clusterSum)

        edgeConcat = pd.concat(sumCosine).groupby(['ComponentIndex', 'scan']).sum().reset_index()
        sums = edgeConcat.groupby('ComponentIndex')['Cosine'].sum().reset_index(name = 'groupSum')
        relativeEdges = edgeConcat.merge(sums, on = 'ComponentIndex', how = 'left')
        relativeEdges['relativeCosine'] = relativeEdges['Cosine']/relativeEdges['groupSum']

        self.edgeWeightings = relativeEdges[['scan', 'relativeCosine']]


class makeNet:
    def __init__(self, edges):
        clustOne = edges.df[['CLUSTERID1', 'ComponentIndex']].rename(columns = {'CLUSTERID1': 'scan', 'ComponentIndex': 'network'})
        clustTwo = edges.df[['CLUSTERID2', 'ComponentIndex']].rename(columns = {'CLUSTERID2': 'scan', 'ComponentIndex': 'network'})

        clusters = [clustOne, clustTwo]
        self.networks = pd.concat(clusters).drop_duplicates()

class selectAnnotation:
    def __init__(self, insilico, network, edgeWeights, analogWeight = True, absoluteMinimum = 0.5, classMinimum = 0.7): # Add absoluteMinimum , etc as argument
        """
        library: The library file merged with network information exported from mergeAnnotations.library
        insilico: The canopus and analog classyfire information merged with network information exported from mergeAnnotations.insilico.
        network: Full network and nodes for adding annotations
        absoluteMinimum: Minimum consensus score for superclass consensus (Defaults to >50%)
        classMinimum: Minimum consensus score for class and subclass (Defaults to >= 70%) 

        library and insilico inputs need to be the direct output of mergeAnnotations()

        This returns a dataframe which has libraryAnnotations and Insilico annotations for every network which meets 
        """
        super().__init__()

        def selectClassy(df, returnType):
            subclassCol = df.index.values[(df.index.str.startswith('subclass') == True) & (df.index.str.endswith('ion') == False)]
            classCol = df.index[(df.index.str.startswith('class') == True) & (df.index.str.endswith('ion') == False)]
            superclassCol = df.index[(df.index.str.startswith('superclass') == True) & (df.index.str.endswith('ion') == False)]
            
            subclassCol = str(subclassCol).split("['")[1]
            subclassCol = str(subclassCol).split("']")[0]

            classCol = str(classCol).split("['")[1]
            classCol = str(classCol).split("']")[0]
            
            superclassCol = str(superclassCol).split("['")[1]
            superclassCol = str(superclassCol).split("']")[0]


            if (df[subclassCol] >= 0.7) & (df[classCol] >= 0.7) & (df[superclassCol] > 0.5) & (df['subclass_annotation'] is not 'None') & (df['subclass_annotation'] is not 'N/A'):
                if returnType == 'annotation':
                    return df['subclass_annotation']
                if returnType == 'score':
                    return df[subclassCol]
                if returnType == 'level':
                    return 'subclass'
 
            elif (df[classCol] >= 0.7) & (df[superclassCol] > 0.5) & (df['class_annotation'] is not 'None') & (df['class_annotation'] is not 'N/A'):
                if returnType == 'annotation':
                    return df['class_annotation']
                if returnType == 'score':
                    return df[classCol]
                if returnType == 'level':
                    return 'class'

            elif (df[superclassCol] > 0.5):
                if returnType == 'annotation':
                    return df['superclass_annotation']
                if returnType == 'score':
                    return df[superclassCol]
                if returnType == 'level':
                    return 'superclass'

        def selectInsilico(insilico, taxLevel, analogWeight):
            canopusCol = str(taxLevel + '_canopus')
            analogCol = str(taxLevel + '_analog')

            if analogWeight == True:
                    if (pd.isnull(insilico['superclass_analog']) == True) & (pd.isnull(insilico['superclass_canopus']) == False):
                        return insilico[canopusCol]
                    elif (pd.isnull(insilico['superclass_analog']) == False) & (pd.isnull(insilico['superclass_canopus']) == True):
                        return  insilico[analogCol]
                    elif (pd.isnull(insilico['superclass_analog']) == False) & (pd.isnull(insilico['superclass_canopus']) == False):
                        return  insilico[analogCol]

            if analogWeight == False:
                    return insilico[canopusCol]


        def filterClassy(data, matchType, weightEdges, absoluteMinimum, classMinimum):
            """
            data: data grouped by network (or featNets)
            matchType: Either library or insilico Matches
            absoluteMinimum: Minimum consensus score for superclass consensus (Defaults to >50%)
            classMinimum: Minimum consensus score for class and subclass (Defaults to >= 70%) 

            """
            if matchType == 'library':
                superclassStr = 'superclass_library'
                classStr = 'class_library'
                subclassStr = 'subclass_library'
                mergeOn = 'featNets'

            if matchType == 'insilico':
                superclassStr = 'superclass_insilico'
                classStr = 'class_insilico'
                subclassStr = 'subclass_insilico'
                mergeOn = 'featNets'

            # Counting the number of Nodes with annotations per network
            groupedData = data.groupby(mergeOn)
            groupCount = groupedData.size().reset_index(name = 'numberOfNodes')

            # caluclating the raw %consensus of annotations per network
            superclassTop = groupedData[superclassStr].apply(lambda x: x.value_counts(normalize = True)).reset_index().rename(columns={'level_1': 'superclass_annotation'})
            classTop = groupedData[classStr].apply(lambda x: x.value_counts(normalize = True)).reset_index().rename(columns={'level_1': 'class_annotation'})
            subclassTop = groupedData[subclassStr].apply(lambda x: x.value_counts(normalize = True)).reset_index().rename(columns={'level_1': 'subclass_annotation'})

            if not weightEdges:
                superclassFiltered = superclassTop[superclassTop[superclassStr] > absoluteMinimum]
                classFiltered = classTop[classTop[classStr] > classMinimum]
                subclassFiltered = subclassTop[subclassTop[subclassStr] > classMinimum]
                merged = superclassFiltered.merge(classFiltered, on = mergeOn, how = 'outer').merge(subclassFiltered, on = mergeOn, how = 'outer').merge(groupCount, on = mergeOn, how = 'left')

            if weightEdges:
                relativeSubclass = str(subclassStr + "Cosine")
                relativeClass = str(classStr + "Cosine")
                relativeSuperclass = str(superclassStr + "Cosine")

                relativeMerged = []

                for x in [0, 1, 2]:
                        newColSeries = []
                        relative = ['relativeSuperclass', 'relativeClass', 'relativeSubclass']
                        raw = [superclassStr, classStr, subclassStr]
                        annotation = ['superclass_annotation', 'class_annotation', 'subclass_annotation']
                        top = [superclassTop, classTop, subclassTop]

                        relativeCheck = relative[x]
                        rawCheck = raw[x]
                        annotationCheck = annotation[x]
                        topCheck = top[x]

                        grouped = data.groupby([mergeOn, rawCheck]).sum().reset_index()
                        relative = grouped[grouped['relativeCosine'] > 0.6][[mergeOn, rawCheck, 'relativeCosine']].rename(columns = {rawCheck: annotationCheck, 'relativeCosine': relativeCheck})
                        mergedWeightings = topCheck.merge(relative, on = [mergeOn, annotationCheck], how = 'left')

                        for index, row in mergedWeightings.iterrows():
                            relativeVal = row[relativeCheck]
                            rawVal = row[rawCheck]
                            newVal = rawVal + 0.1

                            if np.isnan(relativeVal):
                                newColSeries.append(rawVal)

                            if not np.isnan(relativeVal):
                                newColSeries.append(newVal)

                        # Overwrite the superclass with weighted value
                        mergedWeightings[rawCheck] = pd.Series(newColSeries)


                        if x == 0:
                            weightingsFiltered = mergedWeightings[mergedWeightings[rawCheck] > absoluteMinimum]
                            merged = weightingsFiltered
                        if not x == 0:
                            weightingsFiltered = mergedWeightings[mergedWeightings[rawCheck] > classMinimum]
                            merged = merged.merge(weightingsFiltered, on = [mergeOn], how = 'outer')
                        if x == 2:
                            merged = merged.merge(groupCount, on = mergeOn, how = 'left')


            # Merge ontologies and drop NA's
            mergedFiltered = merged.dropna(subset = ['superclass_annotation', 'class_annotation', 'subclass_annotation'], how = 'all')  
            

            mergedFiltered['ecoNetConsensus'] = mergedFiltered.apply(lambda x: selectClassy(x, 'annotation'), axis = 1)
            mergedFiltered['ecoNetConsensusScore'] = mergedFiltered.apply(lambda x: selectClassy(x, 'score'), axis = 1)
            mergedFiltered['ecoNetConsensusLevel'] = mergedFiltered.apply(lambda x: selectClassy(x, 'level'), axis = 1)

            return mergedFiltered

        # Determine if nodes are weighted by edges
        edgesUsed = isinstance(edgeWeights, pd.DataFrame)

        # Need a networks column which has feature numbers for single loop nodes
        insilico.loc[insilico['network'].astype(str).str.contains('-1', regex = False) == True, 'featNets'] = -1 * insilico['scan']
        insilico.loc[insilico['network'].astype(str).str.contains('-1', regex = False) == False, 'featNets'] =  insilico['network']
        singleNodes = insilico[insilico['network'].astype(str).str.contains('-1', regex = False) == True][['scan', 'network', 'featNets']]


        # Selecting annotation from either analog or canopus for insilico usage
        # Need an if statement for finding whether it is just canopus or whether analog is included
        insilicoNulled = insilico.replace(r'^\s*$', 'null', regex=True)

        for col in ['superclass', 'class', 'subclass']:
            newCol = str(col + '_insilico')
            if isinstance(insilicoNulled['class_analog'], pd.Series):
                insilicoNulled[newCol] = insilicoNulled.apply(lambda x: selectInsilico(x, col, analogWeight = True), axis = 1)
            if not isinstance(insilicoNulled['class_analog'], pd.Series):
                insilicoNulled[newCol] = insilicoNulled.apply(lambda x: selectInsilico(x, col, analogWeight = False), axis = 1)

        insilicoCombined = insilicoNulled[['scan', 'featNets', 'superclass_insilico', 'class_insilico', 'subclass_insilico']].reset_index(drop = True).fillna('None')
        
        # group by network and get consensus score
        if edgesUsed:
            insilicoCombined = insilicoCombined.merge(edgeWeights, on = 'scan', how = 'left')
            
        insilicoFiltered = filterClassy(insilicoCombined, 'insilico', edgesUsed, absoluteMinimum, classMinimum) #absoluteMinimum and classMinimum are defined in the main function

        insilicoNoSingle = insilicoFiltered[insilicoFiltered['featNets'] > 0].rename(columns = {'featNets': 'network'})
        insilioSingleNodes = singleNodes.merge(insilicoFiltered, on = 'featNets', how = 'left')[['scan', 'network', 'ecoNetConsensus', 'ecoNetConsensusScore']]
        
        # Combine the library and insilico classyfiltered datafrmes and merge with network        
        insilicoNoSingle['matchSource'] = 'Insilico'
        insilioSingleNodes['matchSource'] = 'Insilico'

        networksMerged = network.merge(insilicoNoSingle, on = 'network', how = 'left')[['scan', 'network', 'ecoNetConsensus', 'ecoNetConsensusScore', 'ecoNetConsensusLevel', 'numberOfNodes', 'matchSource']]

        finalConcat = [networksMerged, insilioSingleNodes]
        self.export =  pd.concat(finalConcat, sort = False)


