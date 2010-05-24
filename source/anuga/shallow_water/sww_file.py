""" Classes to read an SWW file.
"""

from anuga.coordinate_transforms.geo_reference import Geo_reference
from anuga.config import netcdf_mode_r, netcdf_mode_w, netcdf_mode_a
from anuga.config import netcdf_float, netcdf_float32, netcdf_int
from anuga.config import max_float
from anuga.utilities.numerical_tools import ensure_numeric
import anuga.utilities.log as log
from Scientific.IO.NetCDF import NetCDFFile

from anuga.coordinate_transforms.geo_reference import \
        ensure_geo_reference

from file_utils import create_filename
import numpy as num

##
# @brief Generic class for storing output to e.g. visualisation or checkpointing
class Data_format:
    """Generic interface to data formats
    """

    ##
    # @brief Instantiate this instance.
    # @param domain 
    # @param extension 
    # @param mode The mode of the underlying file.
    def __init__(self, domain, extension, mode=netcdf_mode_w):
        assert mode[0] in ['r', 'w', 'a'], \
               "Mode %s must be either:\n" % mode + \
               "   'w' (write)\n" + \
               "   'r' (read)\n" + \
               "   'a' (append)"

        #Create filename
        self.filename = create_filename(domain.get_datadir(),
                                        domain.get_name(), extension)

        self.timestep = 0
        self.domain = domain

        # Exclude ghosts in case this is a parallel domain
        self.number_of_nodes = domain.number_of_full_nodes
        self.number_of_volumes = domain.number_of_full_triangles
        #self.number_of_volumes = len(domain)

        #FIXME: Should we have a general set_precision function?


##
# @brief Class for handling checkpoints data
# @note This is not operational at the moment
class CPT_file(Data_format):
    """Interface to native NetCDF format (.cpt) to be 
    used for checkpointing (one day)
    """

    ##
    # @brief Initialize this instantiation.
    # @param domain ??
    # @param mode Mode of underlying data file (default WRITE).
    def __init__(self, domain, mode=netcdf_mode_w):
        from Scientific.IO.NetCDF import NetCDFFile

        self.precision = netcdf_float #Use full precision

        Data_format.__init__(self, domain, 'sww', mode)

        # NetCDF file definition
        fid = NetCDFFile(self.filename, mode)
        if mode[0] == 'w':
            # Create new file
            fid.institution = 'Geoscience Australia'
            fid.description = 'Checkpoint data'
            #fid.smooth = domain.smooth
            fid.order = domain.default_order

            # Dimension definitions
            fid.createDimension('number_of_volumes', self.number_of_volumes)
            fid.createDimension('number_of_vertices', 3)

            # Store info at all vertices (no smoothing)
            fid.createDimension('number_of_points', 3*self.number_of_volumes)
            fid.createDimension('number_of_timesteps', None) #extensible

            # Variable definitions

            # Mesh
            fid.createVariable('x', self.precision, ('number_of_points',))
            fid.createVariable('y', self.precision, ('number_of_points',))


            fid.createVariable('volumes', netcdf_int, ('number_of_volumes',
                                                       'number_of_vertices'))

            fid.createVariable('time', self.precision, ('number_of_timesteps',))

            #Allocate space for all quantities
            for name in domain.quantities.keys():
                fid.createVariable(name, self.precision,
                                   ('number_of_timesteps',
                                    'number_of_points'))

        fid.close()

    ##
    # @brief Store connectivity data to underlying data file.
    def store_checkpoint(self):
        """Write x,y coordinates of triangles.
        Write connectivity (
        constituting
        the bed elevation.
        """

        from Scientific.IO.NetCDF import NetCDFFile

        domain = self.domain

        #Get NetCDF
        fid = NetCDFFile(self.filename, netcdf_mode_a)

        # Get the variables
        x = fid.variables['x']
        y = fid.variables['y']

        volumes = fid.variables['volumes']

        # Get X, Y and bed elevation Z
        Q = domain.quantities['elevation']
        X,Y,Z,V = Q.get_vertex_values(xy=True, precision=self.precision)

        x[:] = X.astype(self.precision)
        y[:] = Y.astype(self.precision)
        z[:] = Z.astype(self.precision)

        volumes[:] = V

        fid.close()

    ##
    # @brief Store time and named quantities to underlying data file.
    # @param name 
    def store_timestep(self, name):
        """Store time and named quantity to file
        """

        from Scientific.IO.NetCDF import NetCDFFile
        from time import sleep

        #Get NetCDF
        retries = 0
        file_open = False
        while not file_open and retries < 10:
            try:
                fid = NetCDFFile(self.filename, netcdf_mode_a)
            except IOError:
                #This could happen if someone was reading the file.
                #In that case, wait a while and try again
                msg = 'Warning (store_timestep): File %s could not be opened' \
                      ' - trying again' % self.filename
                log.critical(msg)
                retries += 1
                sleep(1)
            else:
                file_open = True

        if not file_open:
            msg = 'File %s could not be opened for append' % self.filename
            raise DataFileNotOpenError, msg

        domain = self.domain

        # Get the variables
        time = fid.variables['time']
        stage = fid.variables['stage']
        i = len(time)

        #Store stage
        time[i] = self.domain.time

        # Get quantity
        Q = domain.quantities[name]
        A,V = Q.get_vertex_values(xy=False, precision=self.precision)

        stage[i,:] = A.astype(self.precision)

        #Flush and close
        fid.sync()
        fid.close()


class SWW_file(Data_format):
    """Interface to native NetCDF format (.sww) for storing model output

    There are two kinds of data

    1: Constant data: Vertex coordinates and field values. Stored once
    2: Variable data: Conserved quantities. Stored once per timestep.

    All data is assumed to reside at vertex locations.
    """

    ##
    # @brief Instantiate this instance.
    # @param domain ??
    # @param mode Mode of the underlying data file.
    # @param max_size ??
    # @param recursion ??
    # @note Prepare the underlying data file if mode starts with 'w'.
    def __init__(self, domain, 
                 mode=netcdf_mode_w, max_size=2000000000, recursion=False):
        from Scientific.IO.NetCDF import NetCDFFile

        self.precision = netcdf_float32 # Use single precision for quantities
        self.recursion = recursion
        self.mode = mode
        if hasattr(domain, 'max_size'):
            self.max_size = domain.max_size # File size max is 2Gig
        else:
            self.max_size = max_size
        if hasattr(domain, 'minimum_storable_height'):
            self.minimum_storable_height = domain.minimum_storable_height
        else:
            self.minimum_storable_height = default_minimum_storable_height

        # Call parent constructor
        Data_format.__init__(self, domain, 'sww', mode)

        # Get static and dynamic quantities from domain
        static_quantities = []
        dynamic_quantities = []
        
        for q in domain.quantities_to_be_stored:
            flag = domain.quantities_to_be_stored[q]
        
            msg = 'Quantity %s is requested to be stored ' % q
            msg += 'but it does not exist in domain.quantities'
            assert q in domain.quantities, msg
        
            assert flag in [1,2]
            if flag == 1: static_quantities.append(q)
            if flag == 2: dynamic_quantities.append(q)                
                       
        
        # NetCDF file definition
        fid = NetCDFFile(self.filename, mode)
        if mode[0] == 'w':
            description = 'Output from anuga.abstract_2d_finite_volumes ' \
                          'suitable for plotting'
                          
            self.writer = Write_sww(static_quantities, dynamic_quantities)
            self.writer.store_header(fid,
                                     domain.starttime,
                                     self.number_of_volumes,
                                     self.domain.number_of_full_nodes,
                                     description=description,
                                     smoothing=domain.smooth,
                                     order=domain.default_order,
                                     sww_precision=self.precision)

            # Extra optional information
            if hasattr(domain, 'texture'):
                fid.texture = domain.texture

            if domain.quantities_to_be_monitored is not None:
                fid.createDimension('singleton', 1)
                fid.createDimension('two', 2)

                poly = domain.monitor_polygon
                if poly is not None:
                    N = len(poly)
                    fid.createDimension('polygon_length', N)
                    fid.createVariable('extrema.polygon',
                                       self.precision,
                                       ('polygon_length', 'two'))
                    fid.variables['extrema.polygon'][:] = poly

                interval = domain.monitor_time_interval
                if interval is not None:
                    fid.createVariable('extrema.time_interval',
                                       self.precision,
                                       ('two',))
                    fid.variables['extrema.time_interval'][:] = interval

                for q in domain.quantities_to_be_monitored:
                    fid.createVariable(q + '.extrema', self.precision,
                                       ('numbers_in_range',))
                    fid.createVariable(q + '.min_location', self.precision,
                                       ('numbers_in_range',))
                    fid.createVariable(q + '.max_location', self.precision,
                                       ('numbers_in_range',))
                    fid.createVariable(q + '.min_time', self.precision,
                                       ('singleton',))
                    fid.createVariable(q + '.max_time', self.precision,
                                       ('singleton',))

        fid.close()

    ##
    # @brief Store connectivity data into the underlying data file.
    def store_connectivity(self):
        """Store information about nodes, triangles and static quantities

        Writes x,y coordinates of triangles and their connectivity.
        
        Store also any quantity that has been identified as static.
        """

        # FIXME: Change name to reflect the fact thta this function 
        # stores both connectivity (triangulation) and static quantities
        
        from Scientific.IO.NetCDF import NetCDFFile

        domain = self.domain

        # append to the NetCDF file
        fid = NetCDFFile(self.filename, netcdf_mode_a)

        # Get X, Y from one (any) of the quantities
        Q = domain.quantities.values()[0]
        X,Y,_,V = Q.get_vertex_values(xy=True, precision=self.precision)

        # store the connectivity data
        points = num.concatenate((X[:,num.newaxis],Y[:,num.newaxis]), axis=1)
        self.writer.store_triangulation(fid,
                                        points,
                                        V.astype(num.float32),
                                        points_georeference=\
                                            domain.geo_reference)


        # Get names of static quantities
        static_quantities = {}
        for name in self.writer.static_quantities:
            Q = domain.quantities[name]
            A, _ = Q.get_vertex_values(xy=False, 
                                       precision=self.precision)
            static_quantities[name] = A
        
        # Store static quantities        
        self.writer.store_static_quantities(fid, **static_quantities)
                                            
        fid.close()

    ##
    # @brief Store time and time dependent quantities 
    # to the underlying data file.
    def store_timestep(self):
        """Store time and time dependent quantities
        """

        from Scientific.IO.NetCDF import NetCDFFile
        import types
        from time import sleep
        from os import stat

        # Get NetCDF
        retries = 0
        file_open = False
        while not file_open and retries < 10:
            try:
                # Open existing file
                fid = NetCDFFile(self.filename, netcdf_mode_a)
            except IOError:
                # This could happen if someone was reading the file.
                # In that case, wait a while and try again
                msg = 'Warning (store_timestep): File %s could not be opened' \
                      % self.filename
                msg += ' - trying step %s again' % self.domain.time
                log.critical(msg)
                retries += 1
                sleep(1)
            else:
                file_open = True

        if not file_open:
            msg = 'File %s could not be opened for append' % self.filename
            raise DataFileNotOpenError, msg

        # Check to see if the file is already too big:
        time = fid.variables['time']
        i = len(time) + 1
        file_size = stat(self.filename)[6]
        file_size_increase = file_size / i
        if file_size + file_size_increase > self.max_size * 2**self.recursion:
            # In order to get the file name and start time correct,
            # I change the domain.filename and domain.starttime.
            # This is the only way to do this without changing
            # other modules (I think).

            # Write a filename addon that won't break the anuga viewers
            # (10.sww is bad)
            filename_ext = '_time_%s' % self.domain.time
            filename_ext = filename_ext.replace('.', '_')

            # Remember the old filename, then give domain a
            # name with the extension
            old_domain_filename = self.domain.get_name()
            if not self.recursion:
                self.domain.set_name(old_domain_filename + filename_ext)

            # Temporarily change the domain starttime to the current time
            old_domain_starttime = self.domain.starttime
            self.domain.starttime = self.domain.get_time()

            # Build a new data_structure.
            next_data_structure = SWW_file(self.domain, mode=self.mode,
                                           max_size=self.max_size,
                                           recursion=self.recursion+1)
            if not self.recursion:
                log.critical('    file_size = %s' % file_size)
                log.critical('    saving file to %s'
                             % next_data_structure.filename) 

            # Set up the new data_structure
            self.domain.writer = next_data_structure

            # Store connectivity and first timestep
            next_data_structure.store_connectivity()
            next_data_structure.store_timestep()
            fid.sync()
            fid.close()

            # Restore the old starttime and filename
            self.domain.starttime = old_domain_starttime
            self.domain.set_name(old_domain_filename)
        else:
            self.recursion = False
            domain = self.domain

            # Get the variables
            time = fid.variables['time']
            i = len(time)
             
            if 'stage' in self.writer.dynamic_quantities:            
                # Select only those values for stage, 
                # xmomentum and ymomentum (if stored) where 
                # depth exceeds minimum_storable_height
                #
                # In this branch it is assumed that elevation
                # is also available as a quantity            
            
                Q = domain.quantities['stage']
                w, _ = Q.get_vertex_values(xy=False)
                
                Q = domain.quantities['elevation']
                z, _ = Q.get_vertex_values(xy=False)                
                
                storable_indices = (w-z >= self.minimum_storable_height)
            else:
                # Very unlikely branch
                storable_indices = None # This means take all
            
            
            # Now store dynamic quantities
            dynamic_quantities = {}
            for name in self.writer.dynamic_quantities:
                netcdf_array = fid.variables[name]
                
                Q = domain.quantities[name]
                A, _ = Q.get_vertex_values(xy=False,
                                           precision=self.precision)

                if storable_indices is not None:
                    if name == 'stage':
                        A = num.choose(storable_indices, (z, A))

                    if name in ['xmomentum', 'ymomentum']:
                        # Get xmomentum where depth exceeds 
                        # minimum_storable_height
                        
                        # Define a zero vector of same size and type as A
                        # for use with momenta
                        null = num.zeros(num.size(A), A.dtype.char)
                        A = num.choose(storable_indices, (null, A))
                
                dynamic_quantities[name] = A
                
                                        
            # Store dynamic quantities
            self.writer.store_quantities(fid,
                                         time=self.domain.time,
                                         sww_precision=self.precision,
                                         **dynamic_quantities)


            # Update extrema if requested
            domain = self.domain
            if domain.quantities_to_be_monitored is not None:
                for q, info in domain.quantities_to_be_monitored.items():
                    if info['min'] is not None:
                        fid.variables[q + '.extrema'][0] = info['min']
                        fid.variables[q + '.min_location'][:] = \
                                        info['min_location']
                        fid.variables[q + '.min_time'][0] = info['min_time']

                    if info['max'] is not None:
                        fid.variables[q + '.extrema'][1] = info['max']
                        fid.variables[q + '.max_location'][:] = \
                                        info['max_location']
                        fid.variables[q + '.max_time'][0] = info['max_time']

            # Flush and close
            fid.sync()
            fid.close()


##
# @brief Class to open an sww file so that domain can be populated with quantity values 
class Read_sww:

    def __init__(self, source):
        """The source parameter is assumed to be a NetCDF sww file.
        """

        self.source = source

        self.frame_number = 0

        fin = NetCDFFile(self.source, 'r')

        self.time = num.array(fin.variables['time'], num.float)
        self.last_frame_number = self.time.shape[0] - 1

        self.frames = num.arange(self.last_frame_number+1)

        fin.close()
        
        self.read_mesh()

        self.quantities = {}

        self.read_quantities()


    def read_mesh(self):
        fin = NetCDFFile(self.source, 'r')

        self.vertices = num.array(fin.variables['volumes'], num.int)
        
        self.x = x = num.array(fin.variables['x'], num.float)
        self.y = y = num.array(fin.variables['y'], num.float)

        assert len(self.x) == len(self.y)
        
        self.xmin = num.min(x)
        self.xmax = num.max(x)
        self.ymin = num.min(y)
        self.ymax = num.max(y)



        fin.close()
        
    def read_quantities(self, frame_number=0):

        assert frame_number >= 0 and frame_number <= self.last_frame_number

        self.frame_number = frame_number

        M = len(self.x)/3
        
        fin = NetCDFFile(self.source, 'r')
        
        for q in filter(lambda n:n != 'x' and n != 'y' and n != 'time' and n != 'volumes' and \
                        '_range' not in n, \
                        fin.variables.keys()):
            if len(fin.variables[q].shape) == 1: # Not a time-varying quantity
                self.quantities[q] = num.ravel(num.array(fin.variables[q], num.float)).reshape(M,3)
            else: # Time-varying, get the current timestep data
                self.quantities[q] = num.array(fin.variables[q][self.frame_number], num.float).reshape(M,3)
        fin.close()
        return self.quantities

    def get_bounds(self):
        return [self.xmin, self.xmax, self.ymin, self.ymax]

    def get_last_frame_number(self):
        return self.last_frame_number

    def get_time(self):
        return self.time[self.frame_number]


# @brief A class to write an SWW file.
class Write_sww:
    from anuga.shallow_water.shallow_water_domain import Domain

    RANGE = '_range'
    EXTREMA = ':extrema'

    ##
    # brief Instantiate the SWW writer class.
    def __init__(self, static_quantities, dynamic_quantities):
        """Initialise Write_sww with two list af quantity names: 
        
        static_quantities (e.g. elevation or friction): 
            Stored once at the beginning of the simulation in a 1D array
            of length number_of_points   
        dynamic_quantities (e.g stage):
            Stored every timestep in a 2D array with 
            dimensions number_of_points X number_of_timesteps        
        
        """
        self.static_quantities = static_quantities   
        self.dynamic_quantities = dynamic_quantities


    ##
    # @brief Store a header in the SWW file.
    # @param outfile Open handle to the file that will be written.
    # @param times A list of time slices *or* a start time.
    # @param number_of_volumes The number of triangles.
    # @param number_of_points The number of points.
    # @param description The internal file description string.
    # @param smoothing True if smoothing is to be used.
    # @param order 
    # @param sww_precision Data type of the quantity written (netcdf constant)
    # @param verbose True if this function is to be verbose.
    # @note If 'times' is a list, the info will be made relative.
    def store_header(self,
                     outfile,
                     times,
                     number_of_volumes,
                     number_of_points,
                     description='Generated by ANUGA',
                     smoothing=True,
                     order=1,
                     sww_precision=netcdf_float32,
                     verbose=False):
        """Write an SWW file header.

        outfile - the open file that will be written
        times - A list of the time slice times OR a start time
        Note, if a list is given the info will be made relative.
        number_of_volumes - the number of triangles
        """

        from anuga.abstract_2d_finite_volumes.util \
            import get_revision_number

        outfile.institution = 'Geoscience Australia'
        outfile.description = description

        # For sww compatibility
        if smoothing is True:
            # Smoothing to be depreciated
            outfile.smoothing = 'Yes'
            outfile.vertices_are_stored_uniquely = 'False'
        else:
            # Smoothing to be depreciated
            outfile.smoothing = 'No'
            outfile.vertices_are_stored_uniquely = 'True'
        outfile.order = order

        try:
            revision_number = get_revision_number()
        except:
            # This will be triggered if the system cannot get the SVN
            # revision number.
            revision_number = None
        # Allow None to be stored as a string
        outfile.revision_number = str(revision_number)

        # This is being used to seperate one number from a list.
        # what it is actually doing is sorting lists from numeric arrays.
        if isinstance(times, (list, num.ndarray)):
            number_of_times = len(times)
            times = ensure_numeric(times)
            if number_of_times == 0:
                starttime = 0
            else:
                starttime = times[0]
                times = times - starttime  #Store relative times
        else:
            number_of_times = 0
            starttime = times


        outfile.starttime = starttime

        # dimension definitions
        outfile.createDimension('number_of_volumes', number_of_volumes)
        outfile.createDimension('number_of_vertices', 3)
        outfile.createDimension('numbers_in_range', 2)

        if smoothing is True:
            outfile.createDimension('number_of_points', number_of_points)
            # FIXME(Ole): This will cause sww files for parallel domains to
            # have ghost nodes stored (but not used by triangles).
            # To clean this up, we have to change get_vertex_values and
            # friends in quantity.py (but I can't be bothered right now)
        else:
            outfile.createDimension('number_of_points', 3*number_of_volumes)

        outfile.createDimension('number_of_timesteps', number_of_times)

        # variable definitions
        outfile.createVariable('x', sww_precision, ('number_of_points',))
        outfile.createVariable('y', sww_precision, ('number_of_points',))

        outfile.createVariable('volumes', netcdf_int, ('number_of_volumes',
                                                       'number_of_vertices'))

        # Doing sww_precision instead of Float gives cast errors.
        outfile.createVariable('time', netcdf_float,
                               ('number_of_timesteps',))

                               
        for q in self.static_quantities:
            
            outfile.createVariable(q, sww_precision,
                                   ('number_of_points',))
            
            outfile.createVariable(q + Write_sww.RANGE, sww_precision,
                                   ('numbers_in_range',))
                                   
            # Initialise ranges with small and large sentinels.
            # If this was in pure Python we could have used None sensibly
            outfile.variables[q+Write_sww.RANGE][0] = max_float  # Min
            outfile.variables[q+Write_sww.RANGE][1] = -max_float # Max

        #if 'elevation' in self.static_quantities:    
        #    # FIXME: Backwards compat - get rid of z once old view has retired
        #    outfile.createVariable('z', sww_precision,
        #                           ('number_of_points',))
                               
        for q in self.dynamic_quantities:
            outfile.createVariable(q, sww_precision, ('number_of_timesteps',
                                                      'number_of_points'))
            outfile.createVariable(q + Write_sww.RANGE, sww_precision,
                                   ('numbers_in_range',))

            # Initialise ranges with small and large sentinels.
            # If this was in pure Python we could have used None sensibly
            outfile.variables[q+Write_sww.RANGE][0] = max_float  # Min
            outfile.variables[q+Write_sww.RANGE][1] = -max_float # Max

        if isinstance(times, (list, num.ndarray)):
            outfile.variables['time'][:] = times    # Store time relative

        if verbose:
            log.critical('------------------------------------------------')
            log.critical('Statistics:')
            log.critical('    t in [%f, %f], len(t) == %d'
                         % (num.min(times), num.max(times), len(times.flat)))

    ##
    # @brief Store triangulation data in the underlying file.
    # @param outfile Open handle to underlying file.
    # @param points_utm List or array of points in UTM.
    # @param volumes 
    # @param zone 
    # @param new_origin georeference that the points can be set to.
    # @param points_georeference The georeference of the points_utm.
    # @param verbose True if this function is to be verbose.
    def store_triangulation(self,
                            outfile,
                            points_utm,
                            volumes,
                            zone=None, 
                            new_origin=None,
                            points_georeference=None, 
                            verbose=False):
        """
        new_origin - qa georeference that the points can be set to. (Maybe
        do this before calling this function.)

        points_utm - currently a list or array of the points in UTM.
        points_georeference - the georeference of the points_utm

        How about passing new_origin and current_origin.
        If you get both, do a convertion from the old to the new.

        If you only get new_origin, the points are absolute,
        convert to relative

        if you only get the current_origin the points are relative, store
        as relative.

        if you get no georefs create a new georef based on the minimums of
        points_utm.  (Another option would be to default to absolute)

        Yes, and this is done in another part of the code.
        Probably geospatial.

        If you don't supply either geo_refs, then supply a zone. If not
        the default zone will be used.

        precon:
            header has been called.
        """

        number_of_points = len(points_utm)
        volumes = num.array(volumes)
        points_utm = num.array(points_utm)

        # Given the two geo_refs and the points, do the stuff
        # described in the method header
        # if this is needed else where, pull out as a function
        points_georeference = ensure_geo_reference(points_georeference)
        new_origin = ensure_geo_reference(new_origin)
        if new_origin is None and points_georeference is not None:
            points = points_utm
            geo_ref = points_georeference
        else:
            if new_origin is None:
                new_origin = Geo_reference(zone, min(points_utm[:,0]),
                                                 min(points_utm[:,1]))
            points = new_origin.change_points_geo_ref(points_utm,
                                                      points_georeference)
            geo_ref = new_origin

        # At this stage I need a georef and points
        # the points are relative to the georef
        geo_ref.write_NetCDF(outfile)

        # This will put the geo ref in the middle
        #geo_ref = Geo_reference(refzone,(max(x)+min(x))/2.0,(max(x)+min(y))/2.)

        x =  points[:,0]
        y =  points[:,1]

        if verbose:
            log.critical('------------------------------------------------')
            log.critical('More Statistics:')
            log.critical('  Extent (/lon):')
            log.critical('    x in [%f, %f], len(lat) == %d'
                         % (min(x), max(x), len(x)))
            log.critical('    y in [%f, %f], len(lon) == %d'
                         % (min(y), max(y), len(y)))
            #log.critical('    z in [%f, %f], len(z) == %d'
            #             % (min(elevation), max(elevation), len(elevation)))
            log.critical('geo_ref: %s' % str(geo_ref))
            log.critical('------------------------------------------------')

        outfile.variables['x'][:] = points[:,0] #- geo_ref.get_xllcorner()
        outfile.variables['y'][:] = points[:,1] #- geo_ref.get_yllcorner()
        outfile.variables['volumes'][:] = volumes.astype(num.int32) #On Opteron 64



    # @brief Write the static quantity data to the underlying file.
    # @param outfile Handle to open underlying file.
    # @param sww_precision Format of quantity data to write (default Float32).
    # @param verbose True if this function is to be verbose.
    # @param **quant
    def store_static_quantities(self, 
                                outfile, 
                                sww_precision=num.float32,
                                verbose=False, 
                                **quant):
        """
        Write the static quantity info.

        **quant is extra keyword arguments passed in. These must be
          the numpy arrays to be stored in the sww file at each timestep.

        The argument sww_precision allows for storing as either 
        * single precision (default): num.float32
        * double precision: num.float64 or num.float 

        Precondition:
            store_triangulation and
            store_header have been called.
        """

        # The dictionary quant must contain numpy arrays for each name.
        # These will typically be quantities from Domain such as friction 
        #
        # Arrays not listed in static_quantitiues will be ignored, silently.
        #
        # This method will also write the ranges for each quantity, 
        # e.g. stage_range, xmomentum_range and ymomentum_range
        for q in self.static_quantities:
            if not quant.has_key(q):
                msg = 'Values for quantity %s was not specified in ' % q
                msg += 'store_quantities so they cannot be stored.'
                raise NewQuantity, msg
            else:
                q_values = ensure_numeric(quant[q])
                
                x = q_values.astype(sww_precision)
                outfile.variables[q][:] = x
        
                # This populates the _range values
                outfile.variables[q + Write_sww.RANGE][0] = num.min(x)
                outfile.variables[q + Write_sww.RANGE][1] = num.max(x)
                    
        # FIXME: Hack for backwards compatibility with old viewer
        #if 'elevation' in self.static_quantities:
        #    outfile.variables['z'][:] = outfile.variables['elevation'][:]

                    
                    
        
        
    ##
    # @brief Write the quantity data to the underlying file.
    # @param outfile Handle to open underlying file.
    # @param sww_precision Format of quantity data to write (default Float32).
    # @param slice_index
    # @param time
    # @param verbose True if this function is to be verbose.
    # @param **quant
    def store_quantities(self, 
                         outfile, 
                         sww_precision=num.float32,
                         slice_index=None,
                         time=None,
                         verbose=False, 
                         **quant):
        """
        Write the quantity info at each timestep.

        **quant is extra keyword arguments passed in. These must be
          the numpy arrays to be stored in the sww file at each timestep.

        if the time array is already been built, use the slice_index
        to specify the index.

        Otherwise, use time to increase the time dimension

        Maybe make this general, but the viewer assumes these quantities,
        so maybe we don't want it general - unless the viewer is general
        
        The argument sww_precision allows for storing as either 
        * single precision (default): num.float32
        * double precision: num.float64 or num.float 

        Precondition:
            store_triangulation and
            store_header have been called.
        """

        if time is not None:
            file_time = outfile.variables['time']
            slice_index = len(file_time)
            file_time[slice_index] = time
        else:
            slice_index = int(slice_index) # Has to be cast in case it was numpy.int    

        # Write the named dynamic quantities
        # The dictionary quant must contain numpy arrays for each name.
        # These will typically be the conserved quantities from Domain 
        # (Typically stage,  xmomentum, ymomentum).
        #
        # Arrays not listed in dynamic_quantitiues will be ignored, silently.
        #
        # This method will also write the ranges for each quantity, 
        # e.g. stage_range, xmomentum_range and ymomentum_range
        for q in self.dynamic_quantities:
            if not quant.has_key(q):
                msg = 'Values for quantity %s was not specified in ' % q
                msg += 'store_quantities so they cannot be stored.'
                raise NewQuantity, msg
            else:
                q_values = ensure_numeric(quant[q])
                
                x = q_values.astype(sww_precision)
                outfile.variables[q][slice_index] = x
                    
        
                # This updates the _range values
                q_range = outfile.variables[q + Write_sww.RANGE][:]
                q_values_min = num.min(q_values)
                if q_values_min < q_range[0]:
                    outfile.variables[q + Write_sww.RANGE][0] = q_values_min
                q_values_max = num.max(q_values)
                if q_values_max > q_range[1]:
                    outfile.variables[q + Write_sww.RANGE][1] = q_values_max

    ##
    # @brief Print the quantities in the underlying file.
    # @param outfile UNUSED.
    def verbose_quantities(self, outfile):
        log.critical('------------------------------------------------')
        log.critical('More Statistics:')
        for q in self.dynamic_quantities:
            log.critical('  %s in [%f, %f]'
                         % (q, outfile.variables[q+Write_sww.RANGE][0],
                            outfile.variables[q+Write_sww.RANGE][1]))
        log.critical('------------------------------------------------')

